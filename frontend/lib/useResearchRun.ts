"use client";

import { useCallback, useRef, useState } from "react";

import { streamResearch, type StreamHandle, type StreamRequest } from "./stream";
import type {
  AgentEvent,
  EvidenceItem,
  ResearchReport,
  RunStatus,
} from "./types";

export interface NodeRecord {
  name: string;
  startedAt?: string;
  endedAt?: string;
  elapsedMs?: number;
}

export interface RunBundle {
  status: RunStatus;
  events: AgentEvent[];
  classification?: AgentEvent["payload"];
  retrievalPlan?: AgentEvent["payload"];
  selectedSections?: string[];
  evidence: EvidenceItem[];
  warnings: string[];
  nodes: NodeRecord[];
  finalReport?: ResearchReport;
  error?: string;
  refused?: boolean;
}

const initial: RunBundle = {
  status: "idle",
  events: [],
  evidence: [],
  warnings: [],
  nodes: [],
};

/** Top-level state machine for a single research run. */
export function useResearchRun() {
  const [bundle, setBundle] = useState<RunBundle>(initial);
  const handleRef = useRef<StreamHandle | null>(null);

  const reset = useCallback(() => {
    setBundle(initial);
  }, []);

  const start = useCallback(
    (request: StreamRequest) => {
      // Ensure any prior run is cancelled
      handleRef.current?.cancel();
      setBundle({ ...initial, status: "streaming" });

      // Optional: hit the sync endpoint as a fallback for tests; here we
      // wire the SSE path which streams operational events.
      const handle = streamResearch(request, {
        onEvent: (evt) => {
          setBundle((prev) => reduce(prev, evt));
        },
        onError: (err) => {
          setBundle((prev) => ({ ...prev, status: "failed", error: err.message }));
        },
        onClose: () => {
          setBundle((prev) =>
            prev.status === "streaming" ? { ...prev, status: "completed" } : prev,
          );
        },
      });
      handleRef.current = handle;
    },
    [],
  );

  const cancel = useCallback(() => {
    handleRef.current?.cancel();
    setBundle((prev) =>
      prev.status === "streaming" ? { ...prev, status: "completed" } : prev,
    );
  }, []);

  return { bundle, start, cancel, reset };
}

// ---------------------------------------------------------------------
// Reducer — folds an incoming AgentEvent into the run bundle
// ---------------------------------------------------------------------
function reduce(prev: RunBundle, evt: AgentEvent): RunBundle {
  const events = [...prev.events, evt];
  switch (evt.type) {
    case "run_started":
      return { ...prev, events, status: "streaming" };

    case "node_start": {
      const name = (evt.payload?.node as string) || evt.node || "node";
      const nodes = upsertNode(prev.nodes, name, { startedAt: evt.timestamp });
      return { ...prev, events, nodes };
    }
    case "node_end": {
      const name = (evt.payload?.node as string) || evt.node || "node";
      const elapsed = evt.payload?.elapsed_ms as number | undefined;
      const nodes = upsertNode(prev.nodes, name, {
        endedAt: evt.timestamp,
        elapsedMs: elapsed,
      });
      return { ...prev, events, nodes };
    }
    case "query_classified": {
      if (evt.payload?.refused) {
        return {
          ...prev,
          events,
          classification: evt.payload,
          refused: true,
          warnings: [...prev.warnings, evt.payload.message as string],
        };
      }
      return { ...prev, events, classification: evt.payload };
    }
    case "retrieval_plan":
      return { ...prev, events, retrievalPlan: evt.payload };

    case "section_selected":
      return {
        ...prev,
        events,
        selectedSections: (evt.payload?.sections as string[]) || prev.selectedSections,
      };

    case "evidence_found": {
      const item = evt.payload as unknown as EvidenceItem;
      // Defensive: schema mismatch tolerance
      const evidence = [...prev.evidence, item];
      return { ...prev, events, evidence };
    }

    case "verification_warning": {
      const w = (evt.payload?.warning as string) || JSON.stringify(evt.payload);
      return { ...prev, events, warnings: [...prev.warnings, w] };
    }

    case "final_report": {
      // Stream sends a *summary* payload; full report comes via the sync
      // /research/query path or is reconstructed from accumulated events.
      // We keep a partial preview for the UI:
      const partial = evt.payload as unknown as Partial<ResearchReport>;
      return {
        ...prev,
        events,
        finalReport: partial && Object.keys(partial).length
          ? ({ ...(prev.finalReport ?? {}), ...partial } as ResearchReport)
          : prev.finalReport,
      };
    }

    case "run_completed":
      return { ...prev, events, status: "completed" };

    case "error":
      return {
        ...prev,
        events,
        status: "failed",
        error: (evt.payload?.error as string) || "stream error",
      };

    default:
      return { ...prev, events };
  }
}

function upsertNode(
  nodes: NodeRecord[],
  name: string,
  patch: Partial<NodeRecord>,
): NodeRecord[] {
  const idx = nodes.findIndex((n) => n.name === name);
  if (idx === -1) return [...nodes, { name, ...patch }];
  const next = [...nodes];
  next[idx] = { ...next[idx], ...patch };
  return next;
}
