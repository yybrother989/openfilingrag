"use client";

import { FileText } from "lucide-react";

import { Badge } from "./ui/Badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./ui/Card";
import type { ResearchReport } from "@/lib/types";

export function ReportCard({ report }: { report: ResearchReport }) {
  return <ReportCardContent report={report} />;
}

export function ReportCardContent({
  report,
  onSelectEvidence,
  selectedEvidenceId,
}: {
  report: ResearchReport;
  onSelectEvidence?: (sourceId: string) => void;
  selectedEvidenceId?: string | null;
}) {
  return (
    <Card className="border-primary/30">
      <CardHeader>
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-primary" />
          <CardTitle>Research memo</CardTitle>
        </div>
        <CardDescription>
          {report.company_name ?? report.ticker ?? "Subject"} · intent{" "}
          <code>{report.intent}</code>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {report.summary ? (
          <section>
            <h4 className="mb-1 text-xs uppercase tracking-wider text-muted-foreground">
              Summary
            </h4>
            <p className="leading-relaxed text-foreground">{report.summary}</p>
          </section>
        ) : null}

        {report.key_findings?.length ? (
          <section>
            <h4 className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">
              Key findings
            </h4>
            <ul className="space-y-2">
              {report.key_findings.map((f, i) => (
                <li
                  key={i}
                  className="rounded-md border border-border/60 bg-muted/30 p-2"
                >
                  <div className="text-foreground">{f.claim}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                    <Badge variant="secondary">{f.confidence}</Badge>
                    {f.evidence_ids.map((e) => (
                      <button
                        key={e}
                        type="button"
                        onClick={() => onSelectEvidence?.(e)}
                        className={selectedEvidenceId === e ? "rounded-md ring-2 ring-primary/40" : ""}
                      >
                        <Badge variant="outline">
                          cite {e.slice(0, 8)}…
                        </Badge>
                      </button>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {report.financial_metrics?.length ? (
          <section>
            <h4 className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">
              Financial metrics referenced
            </h4>
            <ul className="grid grid-cols-2 gap-2">
              {report.financial_metrics.map((m, i) => (
                <li
                  key={i}
                  className="rounded-md border border-border/60 bg-muted/30 p-2 text-xs"
                >
                  <div className="font-medium">{m.metric_name}</div>
                  <div className="text-muted-foreground">
                    {[m.period, m.value, m.change].filter(Boolean).join(" · ")}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {report.risk_factors?.length ? (
          <section>
            <h4 className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">
              Risks disclosed
            </h4>
            <ul className="space-y-1.5">
              {report.risk_factors.map((r, i) => (
                <li
                  key={i}
                  className="flex items-start justify-between gap-2 rounded-md border border-border/60 bg-muted/30 p-2 text-xs"
                >
                  <span>{r.risk}</span>
                  <Badge variant="warning">{r.materiality}</Badge>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {report.management_commentary?.length ? (
          <section>
            <h4 className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">
              Management commentary
            </h4>
            <ul className="space-y-1.5">
              {report.management_commentary.map((c, i) => (
                <li
                  key={i}
                  className="rounded-md border border-border/60 bg-muted/30 p-2 text-xs"
                >
                  <span className="text-muted-foreground">{c.topic}: </span>
                  <span>{c.quote_or_paraphrase}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {report.limitations?.length ? (
          <section>
            <h4 className="mb-1 text-xs uppercase tracking-wider text-muted-foreground">
              Limitations
            </h4>
            <ul className="list-disc pl-4 text-xs text-muted-foreground">
              {report.limitations.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          </section>
        ) : null}

        {report.no_advice_disclaimer ? (
          <p className="border-t border-border/60 pt-2 text-xs italic text-muted-foreground">
            {report.no_advice_disclaimer}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
