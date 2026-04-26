"use client";

import { useEffect, useMemo, useState } from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";
import { Check, ChevronRight, FileText, FileUp, RefreshCw } from "lucide-react";

import { Button } from "./ui/Button";
import { FileTree } from "./FileTree";
import { cn } from "@/lib/utils";
import type { DocumentOut, EdgarFilingsResponse, LocalFileEntry, ResearchControls } from "@/lib/types";

interface Props {
  controls: ResearchControls;
  setControls: Dispatch<SetStateAction<ResearchControls>>;
  documents: DocumentOut[];
  localFiles: LocalFileEntry[];
  activeDocumentIds: number[];
  busy: string | null;
  notice: string | null;
  indexedPathSet: Set<string>;
  onToggleDocument: (documentId: number) => void;
  onSetSelection: (ids: number[]) => void;
  onClearSelection: () => void;
  onInspectDocument: (documentId: number) => void;
  onImportLocalFile: (localPath: string) => Promise<unknown>;
  onReindexDocument: (documentId: number) => Promise<unknown>;
  onDeleteDocument: (documentId: number) => Promise<unknown>;
  onRefresh: () => Promise<void>;
  onPreviewEdgar: (ticker: string, types: string, limit: number) => Promise<EdgarFilingsResponse>;
  onPullEdgar: (ticker: string, types: string[], limit: number) => Promise<unknown>;
  edgarPreview: EdgarFilingsResponse | null;
}

const EDGAR_FORM_OPTIONS = ["10-K", "10-Q", "8-K"];

const STAGE_STORAGE_KEY = "openfilingrag.stage-expanded.v1";
type StageId = "1" | "2" | "3";
type StageState = Record<StageId, boolean>;

export function WorkspaceSidebar(props: Props) {
  const [edgarForms, setEdgarForms] = useState<string[]>(["10-K", "10-Q"]);
  const [edgarLimit, setEdgarLimit] = useState(3);

  const ticker = props.controls.ticker || "";
  const indexedCount = props.documents.length;
  const selectedCount = props.activeDocumentIds.length;
  // All local files (regardless of indexed status) — Local is meant to
  // mirror data/sample_filings/ so users see the full disk picture and
  // each file's indexed/unindexed badge.
  const localFiles = useMemo(
    () => props.localFiles.filter((entry) => entry.kind === "file"),
    [props.localFiles],
  );
  const localCount = localFiles.length;
  const localIndexedCount = useMemo(
    () => localFiles.filter((f) => props.indexedPathSet.has(f.local_path)).length,
    [localFiles, props.indexedPathSet],
  );
  const localUnindexedCount = localCount - localIndexedCount;
  const stage2Hidden = localCount === 0;

  const [expandedStages, setExpandedStages] = useState<StageState>(() =>
    smartDefaults(indexedCount, localUnindexedCount),
  );
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const raw = window.localStorage.getItem(STAGE_STORAGE_KEY);
    if (raw) {
      try {
        const parsed = JSON.parse(raw) as Partial<StageState>;
        setExpandedStages((current) => ({ ...current, ...parsed }));
      } catch {
        window.localStorage.removeItem(STAGE_STORAGE_KEY);
      }
    } else {
      setExpandedStages(smartDefaults(indexedCount, localUnindexedCount));
    }
    setHydrated(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleStage = (id: StageId) => {
    setExpandedStages((current) => {
      const next = { ...current, [id]: !current[id] };
      if (typeof window !== "undefined" && hydrated) {
        window.localStorage.setItem(STAGE_STORAGE_KEY, JSON.stringify(next));
      }
      return next;
    });
  };

  const ingestingPath = props.busy?.startsWith("import:")
    ? props.busy.slice("import:".length)
    : null;

  return (
    <aside className="flex h-full min-h-0 flex-col border-r border-border bg-card/40">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="text-sm font-semibold text-foreground">Workspace</div>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => props.onRefresh()}
          disabled={props.busy === "refresh"}
          title="Refresh"
        >
          <RefreshCw className={cn("h-4 w-4", props.busy === "refresh" && "animate-spin")} />
        </Button>
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto px-3 py-3">
        {/* Stage 1 — Download from EDGAR */}
        <Stage
          label="Download"
          summary={ticker || undefined}
          expanded={expandedStages["1"]}
          onToggle={() => toggleStage("1")}
        >
          <div className="grid grid-cols-[1fr_auto] gap-2">
            <Field label="Ticker">
              <input
                value={ticker}
                onChange={(event) =>
                  props.setControls((current) => ({
                    ...current,
                    ticker: event.target.value.toUpperCase(),
                  }))
                }
                className="workbench-input"
                placeholder="AAPL"
              />
            </Field>
            <Field label="Limit">
              <input
                type="number"
                min={1}
                max={20}
                value={String(edgarLimit)}
                onChange={(event) =>
                  setEdgarLimit(Math.max(1, Math.min(20, Number(event.target.value) || 1)))
                }
                className="workbench-input w-16"
              />
            </Field>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {EDGAR_FORM_OPTIONS.map((form) => {
              const selected = edgarForms.includes(form);
              return (
                <button
                  key={form}
                  type="button"
                  onClick={() =>
                    setEdgarForms((current) =>
                      current.includes(form)
                        ? current.filter((f) => f !== form)
                        : [...current, form],
                    )
                  }
                  className={cn(
                    "rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition-colors",
                    selected
                      ? "border-primary/50 bg-primary/10 text-foreground"
                      : "border-border/70 bg-background/60 text-muted-foreground hover:border-border",
                  )}
                >
                  {form}
                </button>
              );
            })}
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => props.onPreviewEdgar(ticker, edgarForms.join(","), edgarLimit)}
              disabled={!ticker || !edgarForms.length || props.busy === "edgar-preview"}
            >
              Preview
            </Button>
            <Button
              size="sm"
              onClick={() => props.onPullEdgar(ticker, edgarForms, edgarLimit)}
              disabled={!ticker || !edgarForms.length || props.busy === "edgar-pull"}
            >
              {props.busy === "edgar-pull" ? "Pulling…" : "Pull"}
            </Button>
          </div>
          {props.edgarPreview?.filings?.length ? (
            <div className="space-y-1 rounded-md border border-border/70 bg-background/70 p-2">
              {props.edgarPreview.filings.slice(0, 5).map((filing) => (
                <div key={filing.accession_number} className="flex items-baseline justify-between gap-2 text-[11px]">
                  <span className="font-medium text-foreground">{filing.form}</span>
                  <span className="text-muted-foreground">{filing.filing_date}</span>
                </div>
              ))}
            </div>
          ) : null}
        </Stage>

        {/* Stage 2 — Local: every file in data/sample_filings/, with each
            row showing whether it's indexed or still raw on disk. */}
        {stage2Hidden ? null : (
          <Stage
            label="Local"
            summary={
              localIndexedCount === localCount
                ? `${localCount}`
                : `${localCount} · ${localUnindexedCount} new`
            }
            expanded={expandedStages["2"]}
            onToggle={() => toggleStage("2")}
          >
            <div className="space-y-0.5">
              {localFiles.map((file) => {
                const isIndexed = props.indexedPathSet.has(file.local_path);
                const isIngesting = ingestingPath === file.local_path;
                return (
                  <div
                    key={file.local_path}
                    className={cn(
                      "group flex items-center gap-2 rounded-sm px-1.5 py-1 text-xs hover:bg-muted/40",
                      isIndexed && "opacity-70",
                    )}
                    title={file.relative_path}
                  >
                    <FileText
                      className={cn(
                        "h-3.5 w-3.5 shrink-0",
                        isIndexed ? "text-emerald-600/70" : "text-muted-foreground/60",
                      )}
                    />
                    <span className="min-w-0 flex-1 truncate text-foreground">
                      {file.name}
                    </span>
                    {file.size_bytes ? (
                      <span className="shrink-0 text-[10px] text-muted-foreground/60">
                        {formatBytes(file.size_bytes)}
                      </span>
                    ) : null}
                    {isIndexed ? (
                      <span
                        className="inline-flex shrink-0 items-center gap-0.5 rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-400"
                        title="Already part of the indexed corpus"
                      >
                        <Check className="h-2.5 w-2.5" />
                        indexed
                      </span>
                    ) : (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => props.onImportLocalFile(file.local_path)}
                        disabled={Boolean(ingestingPath)}
                        className="h-5 shrink-0 px-1.5 text-[10px]"
                      >
                        <FileUp className="h-3 w-3" />
                        {isIngesting ? "…" : "Ingest"}
                      </Button>
                    )}
                  </div>
                );
              })}
            </div>
          </Stage>
        )}

        {/* ③ Indexed */}
        <Stage
          label="Indexed"
          summary={
            indexedCount === 0
              ? undefined
              : selectedCount === 0
              ? `${indexedCount}`
              : `${selectedCount}/${indexedCount}`
          }
          expanded={expandedStages["3"]}
          onToggle={() => toggleStage("3")}
          action={
            selectedCount > 0 ? (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  props.onClearSelection();
                }}
                className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground hover:text-foreground"
                title="Clear selection"
              >
                clear
              </button>
            ) : null
          }
        >
          <FileTree
            documents={props.documents}
            activeDocumentIds={props.activeDocumentIds}
            onToggleDocument={props.onToggleDocument}
            onSetSelection={props.onSetSelection}
            onInspectDocument={props.onInspectDocument}
            onReindexDocument={props.onReindexDocument}
            onDeleteDocument={props.onDeleteDocument}
          />
        </Stage>

        {props.notice ? (
          <div className="mt-2 rounded-md border border-border/70 bg-background/80 px-3 py-2 text-xs text-muted-foreground">
            {props.notice}
          </div>
        ) : null}
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------
// Stage shell
// ---------------------------------------------------------------------
function Stage({
  label,
  summary,
  expanded,
  onToggle,
  action,
  children,
}: {
  label: string;
  summary?: string;
  expanded: boolean;
  onToggle: () => void;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      className={cn(
        "overflow-hidden rounded-md border border-border/60 bg-background/40",
        expanded && "bg-background/70",
      )}
    >
      {/* Header is a flex row with the toggle as one element and the
          optional action as a sibling — never nest <button> in <button>. */}
      <div className="flex items-center hover:bg-muted/30">
        <button
          type="button"
          onClick={onToggle}
          className="flex flex-1 items-center gap-2 px-3 py-2 text-left"
        >
          <span className="text-sm font-medium text-foreground">{label}</span>
          {summary ? (
            <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
              {summary}
            </span>
          ) : null}
          <ChevronRight
            className={cn(
              "ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
              expanded && "rotate-90",
            )}
          />
        </button>
        {action ? <div className="pr-3">{action}</div> : null}
      </div>
      {expanded ? (
        <div className="space-y-2 border-t border-border/50 px-3 py-2.5">{children}</div>
      ) : null}
    </section>
  );
}

function smartDefaults(indexedCount: number, onDiskCount: number): StageState {
  if (indexedCount === 0 && onDiskCount === 0) return { "1": true, "2": false, "3": false };
  if (indexedCount === 0 && onDiskCount > 0) return { "1": false, "2": true, "3": false };
  if (onDiskCount > 0) return { "1": false, "2": false, "3": true };
  return { "1": false, "2": false, "3": true };
}

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("space-y-1 text-[10px] uppercase tracking-wide text-muted-foreground/80", className)}>
      <span>{label}</span>
      {children}
    </label>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}
