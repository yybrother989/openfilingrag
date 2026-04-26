"use client";

import { useState } from "react";
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  FileText,
  Loader2,
  SearchX,
} from "lucide-react";

import { Badge } from "./ui/Badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./ui/Card";
import type { EvidenceItem } from "@/lib/types";
import { cn, formatScore } from "@/lib/utils";

type RunStatus = "idle" | "streaming" | "completed" | "failed";

interface Props {
  items: EvidenceItem[];
  selectedSourceId?: string | null;
  onSelect?: (sourceId: string) => void;
  status?: RunStatus;
}

/** Right-side: live evidence inspector. Updates as evidence_found events arrive. */
export function EvidenceInspector({
  items,
  selectedSourceId,
  onSelect,
  status = "idle",
}: Props) {
  if (items.length === 0) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-muted-foreground">
        <EmptyState status={status} />
      </div>
    );
  }
  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      {items.map((item) => (
        <EvidenceCard
          key={item.source_id + ":" + item.chunk_index}
          item={item}
          selected={selectedSourceId === item.source_id}
          onSelect={onSelect}
        />
      ))}
      {status === "streaming" ? (
        <div className="flex items-center justify-center py-2">
          <Loader2 className="h-3 w-3 animate-spin text-primary/60" />
        </div>
      ) : null}
    </div>
  );
}

function EmptyState({ status }: { status: RunStatus }) {
  if (status === "streaming") {
    return (
      <div className="space-y-1.5">
        <Loader2 className="mx-auto h-6 w-6 animate-spin text-primary/70" />
        <p className="text-[11px] text-muted-foreground">searching</p>
      </div>
    );
  }
  if (status === "completed") {
    return (
      <div className="space-y-1.5">
        <SearchX className="mx-auto h-6 w-6 opacity-40" />
        <p className="text-[11px] text-muted-foreground">no relevant chunks</p>
      </div>
    );
  }
  if (status === "failed") {
    return (
      <div className="space-y-1.5">
        <AlertCircle className="mx-auto h-6 w-6 text-destructive/70" />
        <p className="text-[11px] text-muted-foreground">run failed</p>
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      <FileText className="mx-auto h-6 w-6 opacity-40" />
      <p className="text-[11px] text-muted-foreground/70">awaiting query</p>
    </div>
  );
}

function EvidenceCard({
  item,
  selected,
  onSelect,
}: {
  item: EvidenceItem;
  selected: boolean;
  onSelect?: (sourceId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const sb = item.score_breakdown ?? {};
  return (
    <Card
      className={cn(
        "border-border/70",
        selected && "border-primary/50 ring-1 ring-primary/30",
      )}
    >
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="space-y-1">
            <CardTitle className="text-xs">
              §{item.section}{" "}
              {item.fiscal_year ? (
                <span className="text-muted-foreground">· FY{item.fiscal_year}</span>
              ) : null}
            </CardTitle>
            <CardDescription className="font-mono">
              {item.ticker} · {item.document_type}
              {item.page_start ? ` · p.${item.page_start}` : ""}
            </CardDescription>
          </div>
          <Badge variant="default">{formatScore(item.relevance_score)}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        <p
          className={cn(
            "whitespace-pre-wrap text-xs leading-relaxed text-foreground/90",
            !open && "line-clamp-5",
          )}
        >
          {item.text}
        </p>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="inline-flex items-center text-xs text-primary hover:text-primary/80"
        >
          {open ? (
            <>
              <ChevronDown className="mr-1 h-3 w-3" />
              Hide full snippet
            </>
          ) : (
            <>
              <ChevronRight className="mr-1 h-3 w-3" />
              Show full snippet
            </>
          )}
        </button>
        {item.retrieval_reason ? (
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            why · {item.retrieval_reason}
          </div>
        ) : null}
        {Object.keys(sb).length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {Object.entries(sb).map(([k, v]) => (
              <Badge key={k} variant="outline">
                {k} {formatScore(Number(v))}
              </Badge>
            ))}
          </div>
        ) : null}
        {(item.metric_tags?.length ?? 0) + (item.risk_tags?.length ?? 0) > 0 ? (
          <div className="flex flex-wrap gap-1">
            {item.metric_tags.map((t) => (
              <Badge key={"m-" + t} variant="secondary">
                #{t}
              </Badge>
            ))}
            {item.risk_tags.map((t) => (
              <Badge key={"r-" + t} variant="warning">
                ⚠ {t}
              </Badge>
            ))}
          </div>
        ) : null}
        <button
          type="button"
          onClick={() => onSelect?.(item.source_id)}
          className="text-xs text-primary hover:text-primary/80"
        >
          Focus evidence
        </button>
      </CardContent>
    </Card>
  );
}
