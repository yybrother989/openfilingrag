"use client";

import { Activity, Brain, FileSearch, Layers, Shield, Sparkles, Triangle } from "lucide-react";

import { Badge } from "./ui/Badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./ui/Card";
import { ReportCard } from "./ReportCard";
import { cn, formatScore, shortText } from "@/lib/utils";
import type { RunBundle } from "@/lib/useResearchRun";

interface Props {
  bundle: RunBundle;
}

/**
 * Center column: shows structured agent-event cards in chronological order:
 *   1. Query classification card
 *   2. Retrieval plan card
 *   3. Selected sections
 *   4. Evidence retrieved (count + collapsed list)
 *   5. Verification warnings
 *   6. Final report (full structured memo)
 */
export function EventTimeline({ bundle }: Props) {
  if (bundle.status === "idle") {
    return (
      <div className="flex h-full items-center justify-center text-center">
        <div className="max-w-md space-y-3 px-6 text-muted-foreground">
          <Sparkles className="mx-auto h-10 w-10 text-primary/60" />
          <h2 className="text-xl font-semibold text-foreground">
            OpenFilingRAG
          </h2>
          <p className="text-sm">
            A filing-aware research agent. Ask a question on the left and watch
            the agent classify, plan, retrieve evidence, verify, and write a
            grounded research memo — live.
          </p>
          <p className="text-xs italic">
            This prototype summarizes company disclosures. It does not provide
            investment advice, ratings, or price targets.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      {bundle.refused ? <RefusalCard message={bundle.warnings[0] ?? ""} /> : null}

      {bundle.classification ? (
        <ClassificationCard payload={bundle.classification} />
      ) : null}

      {bundle.retrievalPlan ? (
        <RetrievalPlanCard payload={bundle.retrievalPlan} />
      ) : null}

      {bundle.selectedSections?.length ? (
        <SectionsCard sections={bundle.selectedSections} />
      ) : null}

      {bundle.evidence.length > 0 ? (
        <EvidenceSummaryCard count={bundle.evidence.length} />
      ) : null}

      {bundle.warnings.length > 0 ? (
        <WarningsCard warnings={bundle.warnings} />
      ) : null}

      {bundle.finalReport ? <ReportCard report={bundle.finalReport} /> : null}

      <NodeTrace nodes={bundle.nodes} />

      {bundle.error ? (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive">Run failed</CardTitle>
            <CardDescription>{bundle.error}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------
// Cards
// ---------------------------------------------------------------------
function RefusalCard({ message }: { message: string }) {
  return (
    <Card className="border-warning">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Shield className="h-4 w-4 text-warning" />
          <CardTitle className="text-warning">Compliance refusal</CardTitle>
        </div>
        <CardDescription>{message}</CardDescription>
      </CardHeader>
    </Card>
  );
}

function ClassificationCard({ payload }: { payload: Record<string, unknown> }) {
  const intent = (payload.intent as string) || "—";
  const ticker = (payload.ticker as string | null) || "—";
  const fy = payload.fiscal_year as number | null | undefined;
  const cross = Boolean(payload.wants_cross_year);
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-primary" />
          <CardTitle>Query classified</CardTitle>
        </div>
        <CardDescription>The agent identified your research intent.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2">
        <Badge variant="default">intent: {intent}</Badge>
        <Badge variant="secondary">ticker: {ticker}</Badge>
        {fy != null ? <Badge variant="secondary">FY: {fy}</Badge> : null}
        {cross ? <Badge variant="warning">cross-year</Badge> : null}
      </CardContent>
    </Card>
  );
}

function RetrievalPlanCard({ payload }: { payload: Record<string, unknown> }) {
  const sections = (payload.preferred_sections as string[]) ?? [];
  const types = (payload.preferred_document_types as string[]) ?? [];
  const metrics = (payload.metric_expansions as string[]) ?? [];
  const risks = (payload.risk_expansions as string[]) ?? [];
  const tablePri = Boolean(payload.table_priority);
  const k = payload.top_k as number | undefined;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-primary" />
          <CardTitle>Retrieval plan</CardTitle>
        </div>
        <CardDescription>
          What the agent decided to fetch given the intent.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex flex-wrap gap-1.5">
          {sections.map((s) => (
            <Badge key={s} variant="default">
              §{s}
            </Badge>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {types.map((t) => (
            <Badge key={t} variant="secondary">
              {t}
            </Badge>
          ))}
        </div>
        {metrics.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            <span className="text-xs text-muted-foreground">metrics:</span>
            {metrics.map((m) => (
              <Badge key={m} variant="outline">
                {m}
              </Badge>
            ))}
          </div>
        ) : null}
        {risks.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            <span className="text-xs text-muted-foreground">risks:</span>
            {risks.map((r) => (
              <Badge key={r} variant="outline">
                {r}
              </Badge>
            ))}
          </div>
        ) : null}
        <div className="flex gap-2 pt-1 text-xs text-muted-foreground">
          {k != null ? <span>top_k = {k}</span> : null}
          {tablePri ? <Badge variant="warning">tables prioritized</Badge> : null}
        </div>
      </CardContent>
    </Card>
  );
}

function SectionsCard({ sections }: { sections: string[] }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <FileSearch className="h-4 w-4 text-primary" />
          <CardTitle>Sections selected</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-1.5">
        {sections.map((s) => (
          <Badge key={s} variant="default">
            §{s}
          </Badge>
        ))}
      </CardContent>
    </Card>
  );
}

function EvidenceSummaryCard({ count }: { count: number }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          <CardTitle>Evidence retrieved</CardTitle>
        </div>
        <CardDescription>
          {count} chunk{count === 1 ? "" : "s"} surfaced. See the right-side
          inspector for snippets, sections, and per-component scores.
        </CardDescription>
      </CardHeader>
    </Card>
  );
}

function WarningsCard({ warnings }: { warnings: string[] }) {
  return (
    <Card className="border-warning/50">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Triangle className="h-4 w-4 text-warning" />
          <CardTitle className="text-warning">Verification warnings</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-1 text-xs text-muted-foreground">
        {warnings.map((w, i) => (
          <div key={i}>· {w}</div>
        ))}
      </CardContent>
    </Card>
  );
}

function NodeTrace({ nodes }: { nodes: RunBundle["nodes"] }) {
  if (nodes.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Node trace</CardTitle>
        <CardDescription>Operational steps the agent took.</CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="space-y-1.5 font-mono text-xs">
          {nodes.map((n) => (
            <li
              key={n.name}
              className={cn(
                "flex items-center justify-between rounded-md border border-border/50 bg-muted/30 px-2 py-1",
                !n.endedAt && "border-primary/40 text-primary",
              )}
            >
              <span>{n.name}</span>
              <span className="text-muted-foreground">
                {n.endedAt ? `${formatScore(n.elapsedMs ?? 0, 0)} ms` : "running"}
              </span>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

// keep eslint quiet about unused
void shortText;
