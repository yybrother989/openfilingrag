"use client";

import { Loader2 } from "lucide-react";

import { EvidenceInspector } from "./EvidenceInspector";
import { Badge } from "./ui/Badge";
import type { DocumentDetailResponse, EvidenceItem } from "@/lib/types";

type RunStatus = "idle" | "streaming" | "completed" | "failed";

const STATUS_TITLE: Record<RunStatus, string> = {
  idle: "Inspector",
  streaming: "Retrieving",
  completed: "Inspector",
  failed: "Inspector",
};

export function ResearchInspector({
  evidence,
  inspectedDocument,
  selectedEvidenceId,
  onSelectEvidence,
  status = "idle",
}: {
  evidence: EvidenceItem[];
  inspectedDocument: DocumentDetailResponse | null;
  selectedEvidenceId?: string | null;
  onSelectEvidence: (sourceId: string) => void;
  status?: RunStatus;
}) {
  const evidenceCount = evidence.length;

  return (
    <aside className="flex h-full min-h-0 flex-col border-l border-border bg-card/30">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <div className="text-sm font-semibold text-foreground">{STATUS_TITLE[status]}</div>
        {status === "streaming" ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
        ) : null}
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {/* Evidence (live) */}
        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              Evidence
            </div>
            {evidenceCount > 0 ? (
              <Badge variant={status === "streaming" ? "default" : "secondary"}>
                {evidenceCount}
              </Badge>
            ) : null}
          </div>
          <div className="min-h-[320px] rounded-md border border-border/70 bg-background/60">
            <EvidenceInspector
              items={evidence}
              selectedSourceId={selectedEvidenceId}
              onSelect={onSelectEvidence}
              status={status}
            />
          </div>
        </section>

        {/* Document */}
        <section className="space-y-2">
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Document
          </div>
          {inspectedDocument ? (
            <div className="rounded-md border border-border/70 bg-background/80 p-3">
              <div className="text-sm font-medium text-foreground">
                {inspectedDocument.document.ticker} · {inspectedDocument.document.document_type}
              </div>
              <div className="text-xs text-muted-foreground">
                {inspectedDocument.document.company_name}
                {inspectedDocument.document.fiscal_year
                  ? ` · FY${inspectedDocument.document.fiscal_year}`
                  : ""}
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {inspectedDocument.sections.slice(0, 8).map((section) => (
                  <Badge key={section.id} variant="outline">
                    {section.canonical_name}
                  </Badge>
                ))}
                {inspectedDocument.sections.length > 8 ? (
                  <Badge variant="outline">
                    +{inspectedDocument.sections.length - 8}
                  </Badge>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="rounded-md border border-dashed border-border/60 bg-background/30 px-3 py-2.5 text-center text-[11px] text-muted-foreground/70">
              none selected
            </div>
          )}
        </section>
      </div>
    </aside>
  );
}
