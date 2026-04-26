"use client";

import { useMemo, useRef, useState } from "react";
import { useLocalRuntime } from "@assistant-ui/react";
import type {
  ChatModelAdapter,
  ChatModelRunResult,
  CompleteAttachment,
  ExportedMessageRepository,
  ThreadAssistantContentPart,
  ThreadMessage,
} from "@assistant-ui/react";

import { API_BASE, ingestUploadFile } from "./api";
import { THREAD_KEY_PREFIX } from "./conversations";
import { framesFromBuffer, parseSSEFrame, readErrorBody } from "./sse";
import type {
  AgentEvent,
  EvidenceItem,
  IngestionResult,
  ResearchControls,
  ResearchReport,
  ScopedResearchRequest,
  ToolCardPayloads,
} from "./types";

const ATTACHMENT_STORAGE_KEY = "openfilingrag.attachment-docs.v1";

type RunStatus = "idle" | "streaming" | "completed" | "failed";

interface RuntimeOptions {
  conversationId: string;
  controls: ResearchControls;
  documentIds: number[];
  onAttachmentIngested: (result: IngestionResult) => Promise<void> | void;
  onUserMessage?: (prompt: string) => void;
}

type ExportedMessageRepositoryItem = ExportedMessageRepository["messages"][number];

function readJson<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  const raw = window.localStorage.getItem(key);
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    window.localStorage.removeItem(key);
    return fallback;
  }
}

function writeJson(key: string, value: unknown) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(key, JSON.stringify(value));
}

function historyKey(conversationId: string): string {
  return THREAD_KEY_PREFIX + conversationId;
}

function restoreHistoryFor(conversationId: string): ExportedMessageRepository {
  const repository = readJson<ExportedMessageRepository>(historyKey(conversationId), {
    messages: [],
  });
  return {
    headId: repository.headId ?? null,
    messages: repository.messages.map((item) => ({
      parentId: item.parentId,
      message: {
        ...item.message,
        createdAt: new Date(item.message.createdAt),
      } as ThreadMessage,
    })),
  };
}

function persistHistoryItemFor(
  conversationId: string,
  item: ExportedMessageRepositoryItem,
) {
  const key = historyKey(conversationId);
  const repository = restoreHistoryFor(conversationId);
  const index = repository.messages.findIndex(
    (entry) => entry.message.id === item.message.id,
  );
  if (index === -1) {
    repository.messages.push(item);
  } else {
    repository.messages[index] = item;
  }
  repository.headId = item.message.id;
  writeJson(key, repository);
}

function restoreAttachmentMap(): Record<string, number> {
  return readJson<Record<string, number>>(ATTACHMENT_STORAGE_KEY, {});
}

function persistAttachmentMap(value: Record<string, number>) {
  writeJson(ATTACHMENT_STORAGE_KEY, value);
}

function makeToolPart<TArgs>(
  toolCallId: string,
  toolName: keyof ToolCardPayloads,
  args: TArgs,
): ThreadAssistantContentPart {
  const argsText = JSON.stringify(args);
  return {
    type: "tool-call",
    toolCallId,
    toolName,
    args: args as never,
    argsText,
    result: args as unknown,
  };
}

function normalizeEvidence(item: EvidenceItem): EvidenceItem {
  return {
    ...item,
    text: item.text || item.snippet || "",
    snippet: item.snippet || item.text || "",
    metric_tags: item.metric_tags || [],
    risk_tags: item.risk_tags || [],
  };
}

function buildRefusalReport(
  query: string,
  payload: ToolCardPayloads["query_classified"],
): ResearchReport {
  return {
    report_id: "refused",
    query,
    ticker: payload.ticker || null,
    company_name: payload.company_name || null,
    intent: payload.intent || "refused_advice",
    summary:
      payload.message ||
      "This system summarizes company disclosures and will not provide investment advice.",
    key_findings: [],
    financial_metrics: [],
    risk_factors: [],
    management_commentary: [],
    evidence: [],
    limitations: ["Advice-oriented questions are refused by policy."],
    validation_warnings: payload.message ? [payload.message] : [],
    no_advice_disclaimer:
      "This prototype summarizes company disclosures and does not provide investment advice, ratings, or price targets.",
    generated_at: new Date().toISOString(),
  };
}

function extractLatestUserMessage(messages: readonly ThreadMessage[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.role === "user") return message;
  }
  return null;
}

function extractPrompt(message: ThreadMessage | null) {
  if (!message || message.role !== "user") return "";
  const parts = message.content
    .filter((part) => part.type === "text")
    .map((part) => part.text.trim())
    .filter(Boolean);
  return parts.join("\n\n").trim();
}

export function useResearchAssistantRuntime(options: RuntimeOptions) {
  const [status, setStatus] = useState<RunStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<EvidenceItem[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);

  const conversationId = options.conversationId;
  const controlsRef = useRef(options.controls);
  const documentIdsRef = useRef(options.documentIds);
  const onAttachmentIngestedRef = useRef(options.onAttachmentIngested);
  const onUserMessageRef = useRef(options.onUserMessage);
  const attachmentMapRef = useRef<Record<string, number>>(restoreAttachmentMap());

  controlsRef.current = options.controls;
  documentIdsRef.current = options.documentIds;
  onAttachmentIngestedRef.current = options.onAttachmentIngested;
  onUserMessageRef.current = options.onUserMessage;

  // History adapter is keyed to the conversationId. Parent should pass
  // `key={conversationId}` to whichever component owns this hook so a
  // switch tears the runtime down and back up cleanly.
  const historyAdapter = useMemo(
    () => ({
      load: async () => restoreHistoryFor(conversationId),
      append: async (item: ExportedMessageRepositoryItem) => {
        persistHistoryItemFor(conversationId, item);
        // Notify parent on user messages so the conversation index can
        // promote this thread to the top + set its title from the first
        // prompt.
        if (item.message.role === "user") {
          const text = item.message.content
            ?.filter((p): p is { type: "text"; text: string } => p.type === "text")
            .map((p) => p.text)
            .join(" ")
            .trim();
          onUserMessageRef.current?.(text || "");
        }
      },
    }),
    [conversationId],
  );

  const attachmentsAdapter = useMemo(
    () => ({
      accept: ".pdf,.html,.htm,.txt,.md",
      add: async ({ file }: { file: File }) => ({
        id: crypto.randomUUID(),
        type: "document" as const,
        name: file.name,
        contentType: file.type || "application/octet-stream",
        file,
        status: { type: "requires-action" as const, reason: "composer-send" as const },
      }),
      remove: async (attachment: { id: string }) => {
        delete attachmentMapRef.current[attachment.id];
        persistAttachmentMap(attachmentMapRef.current);
      },
      send: async (attachment: {
        id: string;
        name: string;
        contentType: string;
        file: File;
      }): Promise<CompleteAttachment> => {
        const current = controlsRef.current;
        const result = await ingestUploadFile({
          ticker: current.ticker,
          company_name: current.company_name || current.ticker || "Local Filing",
          document_type: "10-K",
          file: attachment.file,
        });
        attachmentMapRef.current[attachment.id] = result.document_id;
        persistAttachmentMap(attachmentMapRef.current);
        await onAttachmentIngestedRef.current(result);
        return {
          id: attachment.id,
          type: "document",
          name: attachment.name,
          contentType: attachment.contentType,
          status: { type: "complete" },
          content: [
            {
              type: "text",
              text: `Indexed attachment ${attachment.name} as document ${result.document_id}.`,
            },
          ],
        };
      },
    }),
    [],
  );

  const adapter = useMemo<ChatModelAdapter>(
    () => ({
      run: async function* ({
        messages,
        abortSignal,
      }: {
        messages: readonly ThreadMessage[];
        abortSignal: AbortSignal;
      }): AsyncGenerator<ChatModelRunResult, void, unknown> {
        const userMessage = extractLatestUserMessage(messages);
        const query = extractPrompt(userMessage);
        const attachmentIds =
          userMessage?.role === "user"
            ? (userMessage.attachments || []).map((attachment) => attachment.id)
            : [];
        const scopedAttachmentDocumentIds = attachmentIds
          .map((id) => attachmentMapRef.current[id])
          .filter((value): value is number => Boolean(value));
        const request: ScopedResearchRequest = {
          query,
          ticker: controlsRef.current.ticker || undefined,
          company_name: controlsRef.current.company_name || undefined,
          document_ids: Array.from(
            new Set([...documentIdsRef.current, ...scopedAttachmentDocumentIds]),
          ).sort((a, b) => a - b),
        };

        setStatus("streaming");
        setError(null);
        setEvidence([]);
        setWarnings([]);
        setReport(null);
        setSelectedEvidenceId(null);

        const selectedSections: ToolCardPayloads["section_selected"] = { sections: [] };
        const evidenceBucket: ToolCardPayloads["retrieve_evidence"] = { items: [] };
        const warningBucket: ToolCardPayloads["verification_warning"] = { warnings: [] };
        let currentClassification: ToolCardPayloads["query_classified"] | null = null;
        let currentPlan: ToolCardPayloads["retrieval_plan"] | null = null;
        let currentReport: ResearchReport | null = null;

        const buildContent = () => {
          const content: ThreadAssistantContentPart[] = [];
          if (!currentClassification && !currentPlan && evidenceBucket.items.length === 0) {
            content.push({
              type: "text" as const,
              text: "Running filing-aware research on the local corpus.",
            });
          }
          if (currentClassification) {
            content.push(
              makeToolPart("query_classified", "query_classified", currentClassification),
            );
          }
          if (currentPlan) {
            content.push(makeToolPart("retrieval_plan", "retrieval_plan", currentPlan));
          }
          if (selectedSections.sections.length > 0) {
            content.push(
              makeToolPart("section_selected", "section_selected", selectedSections),
            );
          }
          if (evidenceBucket.items.length > 0) {
            content.push(
              makeToolPart("retrieve_evidence", "retrieve_evidence", evidenceBucket),
            );
          }
          if (warningBucket.warnings.length > 0) {
            content.push(
              makeToolPart(
                "verification_warning",
                "verification_warning",
                warningBucket,
              ),
            );
          }
          if (currentReport) {
            content.push(makeToolPart("final_report", "final_report", currentReport));
          }
          return content;
        };

        const response = await fetch(`${API_BASE}/research/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
          body: JSON.stringify(request),
          signal: abortSignal,
        });
        if (!response.ok || !response.body) {
          const detail = await readErrorBody(response);
          throw new Error(
            detail
              ? `stream HTTP ${response.status}: ${detail}`
              : `stream HTTP ${response.status}`,
          );
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const { frames, rest } = framesFromBuffer(buffer);
            buffer = rest;
            for (const frame of frames) {
              const event = parseSSEFrame<AgentEvent>(frame);
              if (!event) continue;

              if (event.type === "query_classified") {
                currentClassification =
                  event.payload as unknown as ToolCardPayloads["query_classified"];
                if (currentClassification.refused) {
                  currentReport = buildRefusalReport(query, currentClassification);
                  setWarnings(currentClassification.message ? [currentClassification.message] : []);
                  setReport(currentReport);
                }
              }

              if (event.type === "retrieval_plan") {
                currentPlan =
                  event.payload as unknown as ToolCardPayloads["retrieval_plan"];
              }

              if (event.type === "section_selected") {
                selectedSections.sections =
                  (event.payload.sections as string[]) || selectedSections.sections;
              }

              if (event.type === "evidence_found") {
                const nextItem = normalizeEvidence(event.payload as unknown as EvidenceItem);
                evidenceBucket.items = [...evidenceBucket.items, nextItem];
                setEvidence(evidenceBucket.items);
              }

              if (event.type === "verification_warning") {
                const warning =
                  typeof event.payload.warning === "string"
                    ? event.payload.warning
                    : JSON.stringify(event.payload);
                warningBucket.warnings = [...warningBucket.warnings, warning];
                setWarnings(warningBucket.warnings);
              }

              if (event.type === "final_report") {
                currentReport = event.payload as unknown as ResearchReport;
                setReport(currentReport);
                if (currentReport.evidence?.length) {
                  setEvidence(currentReport.evidence.map(normalizeEvidence));
                  evidenceBucket.items = currentReport.evidence.map(normalizeEvidence);
                }
                if (currentReport.validation_warnings?.length) {
                  warningBucket.warnings = currentReport.validation_warnings;
                  setWarnings(currentReport.validation_warnings);
                }
              }

              if (event.type === "error") {
                const message =
                  typeof event.payload.error === "string"
                    ? event.payload.error
                    : "stream error";
                setStatus("failed");
                setError(message);
                yield {
                  content: [
                    ...buildContent(),
                    { type: "text" as const, text: `Run failed: ${message}` },
                  ],
                  status: { type: "incomplete" as const, reason: "error" as const, error: message },
                };
                return;
              }

              if (
                event.type === "query_classified" ||
                event.type === "retrieval_plan" ||
                event.type === "section_selected" ||
                event.type === "evidence_found" ||
                event.type === "verification_warning" ||
                event.type === "final_report"
              ) {
                yield {
                  content: buildContent(),
                  status: { type: "running" as const },
                };
              }
            }
          }

          setStatus("completed");
          yield {
            content: buildContent(),
            status: { type: "complete" as const, reason: "unknown" as const },
          };
        } catch (caught) {
          if (caught instanceof Error && caught.name === "AbortError") {
            throw caught;
          }
          const message =
            caught instanceof Error ? caught.message : "Unexpected runtime failure";
          setStatus("failed");
          setError(message);
          yield {
            content: [
              ...buildContent(),
              { type: "text" as const, text: `Run failed: ${message}` },
            ],
            status: { type: "incomplete" as const, reason: "error" as const, error: message },
          };
        }
      },
    }),
    [],
  );

  const runtime = useLocalRuntime(adapter, {
    adapters: {
      history: historyAdapter,
      attachments: attachmentsAdapter,
    },
  });

  return {
    runtime,
    status,
    error,
    evidence,
    warnings,
    report,
    selectedEvidenceId,
    setSelectedEvidenceId,
  };
}
