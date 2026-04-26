"use client";

import type { ReactNode } from "react";
import { makeAssistantToolUI } from "@assistant-ui/react";
import { Brain, FileSearch, Layers, Shield, Triangle } from "lucide-react";

import { ReportCardContent } from "./ReportCard";
import { Badge } from "./ui/Badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/Card";
import { formatScore, shortText } from "@/lib/utils";
import type { ToolCardPayloads } from "@/lib/types";

function Frame({
  icon,
  title,
  description,
  children,
  warning,
}: {
  icon: React.ReactNode;
  title: string;
  description?: string;
  children: ReactNode;
  warning?: boolean;
}) {
  return (
    <Card className={warning ? "border-warning/50" : "border-border/70"}>
      <CardHeader>
        <div className="flex items-center gap-2">
          {icon}
          <CardTitle className={warning ? "text-warning" : ""}>{title}</CardTitle>
        </div>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent className="space-y-3">{children}</CardContent>
    </Card>
  );
}

export function createResearchToolUIs(options: {
  onSelectEvidence: (sourceId: string) => void;
  selectedEvidenceId?: string | null;
}) {
  return [
    makeAssistantToolUI<ToolCardPayloads["query_classified"], ToolCardPayloads["query_classified"]>({
      toolName: "query_classified",
      render: ({ args }) => {
        if (args.refused) {
          return (
            <Frame
              icon={<Shield className="h-4 w-4 text-warning" />}
              title="Compliance refusal"
              description={args.message}
              warning
            >
              <div className="text-xs text-muted-foreground">
                Advice-oriented prompts are blocked before retrieval starts.
              </div>
            </Frame>
          );
        }
        return (
          <Frame
            icon={<Brain className="h-4 w-4 text-primary" />}
            title="Query classified"
            description="The runtime resolved intent and active scope."
          >
            <div className="flex flex-wrap gap-2">
              <Badge variant="default">intent: {args.intent}</Badge>
              {args.ticker ? <Badge variant="secondary">ticker: {args.ticker}</Badge> : null}
              {args.fiscal_year ? <Badge variant="secondary">FY: {args.fiscal_year}</Badge> : null}
              {args.document_ids?.length ? (
                <Badge variant="outline">{args.document_ids.length} scoped doc(s)</Badge>
              ) : null}
              {args.wants_cross_year ? <Badge variant="warning">cross-year</Badge> : null}
            </div>
          </Frame>
        );
      },
    }),
    makeAssistantToolUI<ToolCardPayloads["retrieval_plan"], ToolCardPayloads["retrieval_plan"]>({
      toolName: "retrieval_plan",
      render: ({ args }) => (
        <Frame
          icon={<Layers className="h-4 w-4 text-primary" />}
          title="Retrieval plan"
          description="Preferred sections, sources, and retrieval depth."
        >
          <div className="flex flex-wrap gap-1.5">
            {args.preferred_sections.map((section) => (
              <Badge key={section} variant="default">
                {section}
              </Badge>
            ))}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {args.preferred_document_types.map((type) => (
              <Badge key={type} variant="secondary">
                {type}
              </Badge>
            ))}
            {args.document_ids?.length ? (
              <Badge variant="outline">hard scope: {args.document_ids.join(", ")}</Badge>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-1.5 text-xs text-muted-foreground">
            {args.metric_expansions.map((metric) => (
              <span key={metric}>metric:{metric}</span>
            ))}
            {args.risk_expansions.map((risk) => (
              <span key={risk}>risk:{risk}</span>
            ))}
          </div>
          <div className="text-xs text-muted-foreground">
            top_k {args.top_k || "auto"} {args.table_priority ? "· tables prioritized" : ""}
          </div>
        </Frame>
      ),
    }),
    makeAssistantToolUI<ToolCardPayloads["section_selected"], ToolCardPayloads["section_selected"]>({
      toolName: "section_selected",
      render: ({ args }) => (
        <Frame
          icon={<FileSearch className="h-4 w-4 text-primary" />}
          title="Sections selected"
        >
          <div className="flex flex-wrap gap-1.5">
            {args.sections.map((section) => (
              <Badge key={section} variant="default">
                {section}
              </Badge>
            ))}
          </div>
        </Frame>
      ),
    }),
    makeAssistantToolUI<ToolCardPayloads["retrieve_evidence"], ToolCardPayloads["retrieve_evidence"]>({
      toolName: "retrieve_evidence",
      render: ({ args }) => (
        <Frame
          icon={<FileSearch className="h-4 w-4 text-primary" />}
          title="Evidence retrieved"
          description={`${args.items.length} snippet${args.items.length === 1 ? "" : "s"} currently in scope.`}
        >
          <div className="space-y-2">
            {args.items.slice(0, 4).map((item) => (
              <button
                key={`${item.source_id}:${item.chunk_index}`}
                type="button"
                onClick={() => options.onSelectEvidence(item.source_id)}
                className="block w-full rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-left hover:border-primary/40 hover:bg-muted/40"
              >
                <div className="flex items-center justify-between gap-3 text-xs">
                  <span className="font-medium text-foreground">
                    {item.section} · {item.document_type}
                  </span>
                  <span className="text-muted-foreground">
                    {formatScore(item.relevance_score)}
                  </span>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {shortText(item.snippet || item.text, 180)}
                </div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {item.metric_tags.slice(0, 2).map((tag) => (
                    <Badge key={`metric:${tag}`} variant="secondary">
                      {tag}
                    </Badge>
                  ))}
                  {item.risk_tags.slice(0, 2).map((tag) => (
                    <Badge key={`risk:${tag}`} variant="warning">
                      {tag}
                    </Badge>
                  ))}
                  {options.selectedEvidenceId === item.source_id ? (
                    <Badge variant="outline">focused</Badge>
                  ) : null}
                </div>
              </button>
            ))}
          </div>
        </Frame>
      ),
    }),
    makeAssistantToolUI<ToolCardPayloads["verification_warning"], ToolCardPayloads["verification_warning"]>({
      toolName: "verification_warning",
      render: ({ args }) => (
        <Frame
          icon={<Triangle className="h-4 w-4 text-warning" />}
          title="Verification warnings"
          description="The workflow flagged evidence or validation issues."
          warning
        >
          <div className="space-y-1 text-xs text-muted-foreground">
            {args.warnings.map((warning, index) => (
              <div key={`${warning}:${index}`}>· {warning}</div>
            ))}
          </div>
        </Frame>
      ),
    }),
    makeAssistantToolUI<ToolCardPayloads["final_report"], ToolCardPayloads["final_report"]>({
      toolName: "final_report",
      render: ({ args }) => (
        <ReportCardContent
          report={args}
          onSelectEvidence={options.onSelectEvidence}
          selectedEvidenceId={options.selectedEvidenceId}
        />
      ),
    }),
  ];
}
