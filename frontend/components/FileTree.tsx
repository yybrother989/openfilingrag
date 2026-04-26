"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import {
  ChevronDown,
  ChevronRight,
  Eye,
  FileText,
  Folder,
  FolderOpen,
  RefreshCw,
  Trash2,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { DocumentOut } from "@/lib/types";

interface Props {
  documents: DocumentOut[];
  activeDocumentIds: number[];
  onToggleDocument: (id: number) => void;
  onSetSelection: (ids: number[]) => void;
  onInspectDocument: (id: number) => void;
  onReindexDocument: (id: number) => Promise<unknown>;
  onDeleteDocument: (id: number) => Promise<unknown>;
}

// ---------------------------------------------------------------------
// Node model
// ---------------------------------------------------------------------
type NodeKind = "folder" | "indexed";

interface TreeNode {
  id: string;
  kind: NodeKind;
  label: string;
  children?: TreeNode[];
  document?: DocumentOut;
}

interface ContextMenuState {
  x: number;
  y: number;
  documentId: number;
  selectionIds: number[]; // doc ids the menu acts on (multi-select aware)
}

/**
 * VS Code-style file tree with multi-select (Cmd/Ctrl+click toggle,
 * Shift+click range, marquee drag) and a right-click context menu.
 */
export function FileTree({
  documents,
  activeDocumentIds,
  onToggleDocument,
  onSetSelection,
  onInspectDocument,
  onReindexDocument,
  onDeleteDocument,
}: Props) {
  const tree = useMemo(() => buildTree(documents), [documents]);

  // Visible-order list of indexed file ids — used for shift-range and
  // marquee. Folders that are collapsed contribute nothing.
  const [expanded, setExpanded] = useState<Set<string>>(
    () => collectFolderIds(tree),
  );
  const visibleIndexedOrder = useMemo(
    () => collectVisibleIndexedIds(tree, expanded),
    [tree, expanded],
  );

  const lastClickedIdRef = useRef<number | null>(null);
  const treeContainerRef = useRef<HTMLDivElement>(null);

  // ---------- Marquee state ----------
  const [marquee, setMarquee] = useState<MarqueeRect | null>(null);
  const marqueeAnchorRef = useRef<{ x: number; y: number } | null>(null);
  const marqueeBaseSelectionRef = useRef<Set<number>>(new Set());

  // ---------- Context menu ----------
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);

  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    document.addEventListener("click", close);
    document.addEventListener("contextmenu", close);
    document.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("click", close);
      document.removeEventListener("contextmenu", close);
      document.removeEventListener("scroll", close, true);
    };
  }, [contextMenu]);

  const toggleFolder = (id: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  // Multi-select click handler — called on label/file-row click.
  const onFileClick = (id: number, e: ReactMouseEvent) => {
    const isMeta = e.metaKey || e.ctrlKey;
    const isShift = e.shiftKey;

    if (isShift && lastClickedIdRef.current !== null) {
      // Range select between lastClickedId and id, additive to current
      const range = idsInRange(
        visibleIndexedOrder,
        lastClickedIdRef.current,
        id,
      );
      const next = new Set(activeDocumentIds);
      for (const r of range) next.add(r);
      onSetSelection([...next]);
      return;
    }

    if (isMeta) {
      // Toggle individual additively
      onToggleDocument(id);
      lastClickedIdRef.current = id;
      return;
    }

    // No modifier → inspect (preserve existing behavior)
    onInspectDocument(id);
    lastClickedIdRef.current = id;
  };

  // ---------- Marquee handlers ----------
  const onContainerMouseDown = (e: ReactMouseEvent) => {
    // Only start a marquee on plain left-click in empty space
    if (e.button !== 0) return;
    const target = e.target as HTMLElement;
    if (target.closest("[data-tree-row]") || target.closest("button") || target.closest("input")) {
      return;
    }
    const container = treeContainerRef.current;
    if (!container) return;

    marqueeAnchorRef.current = { x: e.clientX, y: e.clientY };
    // Cmd/Ctrl/Shift extends current selection; plain drag replaces
    marqueeBaseSelectionRef.current =
      e.metaKey || e.ctrlKey || e.shiftKey
        ? new Set(activeDocumentIds)
        : new Set();
    setMarquee({ x0: e.clientX, y0: e.clientY, x1: e.clientX, y1: e.clientY });
    e.preventDefault();

    const onMove = (ev: globalThis.MouseEvent) => {
      const anchor = marqueeAnchorRef.current;
      if (!anchor) return;
      setMarquee({ x0: anchor.x, y0: anchor.y, x1: ev.clientX, y1: ev.clientY });
      // Recompute selection from base + intersected rows
      const rect = normalizeRect(anchor.x, anchor.y, ev.clientX, ev.clientY);
      const hit = collectIntersectingDocIds(rect);
      const next = new Set(marqueeBaseSelectionRef.current);
      for (const id of hit) next.add(id);
      onSetSelection([...next]);
    };
    const onUp = () => {
      marqueeAnchorRef.current = null;
      setMarquee(null);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const onFileContextMenu = (id: number, e: ReactMouseEvent) => {
    e.preventDefault();
    // If the right-clicked file is part of the current selection, the
    // menu acts on the whole selection. Otherwise it acts on just this
    // file (and shifts focus to it without altering selection).
    const inSelection = activeDocumentIds.includes(id);
    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      documentId: id,
      selectionIds: inSelection ? [...activeDocumentIds] : [id],
    });
  };

  if (tree.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border/60 bg-background/30 px-3 py-2.5 text-center text-[11px] text-muted-foreground/70">
        empty
      </div>
    );
  }

  return (
    <>
      <div
        ref={treeContainerRef}
        onMouseDown={onContainerMouseDown}
        className="relative select-none rounded-md border border-border/70 bg-background/60 py-1"
      >
        {tree.map((node) => (
          <Node
            key={node.id}
            node={node}
            depth={0}
            expanded={expanded}
            onToggleFolder={toggleFolder}
            activeDocumentIds={activeDocumentIds}
            onFileClick={onFileClick}
            onFileContextMenu={onFileContextMenu}
            onToggleDocument={onToggleDocument}
          />
        ))}

        {marquee ? (
          <div
            className="pointer-events-none fixed z-40 border border-primary/50 bg-primary/10"
            style={{
              left: Math.min(marquee.x0, marquee.x1),
              top: Math.min(marquee.y0, marquee.y1),
              width: Math.abs(marquee.x1 - marquee.x0),
              height: Math.abs(marquee.y1 - marquee.y0),
            }}
          />
        ) : null}
      </div>

      {contextMenu ? (
        <ContextMenu
          state={contextMenu}
          onClose={() => setContextMenu(null)}
          onInspect={() => {
            onInspectDocument(contextMenu.documentId);
            setContextMenu(null);
          }}
          onReindex={async () => {
            const ids = contextMenu.selectionIds;
            setContextMenu(null);
            // Sequential — reindex is heavy, parallelism would hammer LLM/DB
            for (const id of ids) {
              try {
                await onReindexDocument(id);
              } catch {
                // workspace surfaces the notice
                break;
              }
            }
          }}
          onDelete={async () => {
            const ids = contextMenu.selectionIds;
            const count = ids.length;
            const ok = window.confirm(
              count === 1
                ? "Delete this filing? This drops its chunks and cached evidence."
                : `Delete ${count} filings? This drops their chunks and cached evidence.`,
            );
            setContextMenu(null);
            if (!ok) return;
            for (const id of ids) {
              try {
                await onDeleteDocument(id);
              } catch {
                break;
              }
            }
          }}
        />
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------------
// Recursive row
// ---------------------------------------------------------------------
function Node({
  node,
  depth,
  expanded,
  onToggleFolder,
  activeDocumentIds,
  onFileClick,
  onFileContextMenu,
  onToggleDocument,
}: {
  node: TreeNode;
  depth: number;
  expanded: Set<string>;
  onToggleFolder: (id: string) => void;
  activeDocumentIds: number[];
  onFileClick: (id: number, e: ReactMouseEvent) => void;
  onFileContextMenu: (id: number, e: ReactMouseEvent) => void;
  onToggleDocument: (id: number) => void;
}) {
  const indentPx = 8 + depth * 14;

  if (node.kind === "folder") {
    const open = expanded.has(node.id);
    const counts = summarizeFolder(node);
    return (
      <div>
        <button
          type="button"
          onClick={() => onToggleFolder(node.id)}
          className="group flex w-full items-center gap-1.5 rounded-sm px-1 py-1 text-left text-xs hover:bg-muted/60"
          style={{ paddingLeft: indentPx }}
        >
          {open ? (
            <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
          )}
          {open ? (
            <FolderOpen className="h-3.5 w-3.5 shrink-0 text-amber-600/80" />
          ) : (
            <Folder className="h-3.5 w-3.5 shrink-0 text-amber-600/80" />
          )}
          <span className="truncate font-medium text-foreground">{node.label}</span>
          {counts.label ? (
            <span className="ml-auto pl-2 text-[10px] text-muted-foreground/70">
              {counts.label}
            </span>
          ) : null}
        </button>
        {open && node.children
          ? node.children.map((child) => (
              <Node
                key={child.id}
                node={child}
                depth={depth + 1}
                expanded={expanded}
                onToggleFolder={onToggleFolder}
                activeDocumentIds={activeDocumentIds}
                onFileClick={onFileClick}
                onFileContextMenu={onFileContextMenu}
                onToggleDocument={onToggleDocument}
              />
            ))
          : null}
      </div>
    );
  }

  if (node.kind === "indexed" && node.document) {
    const doc = node.document;
    const selected = activeDocumentIds.includes(doc.id);
    return (
      <div
        data-tree-row
        data-doc-id={doc.id}
        onContextMenu={(e) => onFileContextMenu(doc.id, e)}
        className={cn(
          "group flex items-center gap-1.5 rounded-sm py-1 pr-1 text-xs hover:bg-muted/40",
          selected && "bg-primary/10",
        )}
        style={{ paddingLeft: indentPx + 12 }}
      >
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggleDocument(doc.id)}
          onClick={(e) => e.stopPropagation()}
          className="size-3.5 shrink-0 cursor-pointer"
          aria-label={`Include ${doc.ticker} ${doc.document_type} in query scope`}
        />
        <FileText className="h-3.5 w-3.5 shrink-0 text-sky-600/80" />
        <button
          type="button"
          onClick={(e) => onFileClick(doc.id, e)}
          className="min-w-0 flex-1 truncate text-left text-foreground"
          title="Click to inspect · Cmd/Ctrl-click to multi-select · Shift-click for range · Right-click for actions"
        >
          <span className="font-medium">{doc.document_type}</span>
          {doc.fiscal_year ? (
            <span className="text-muted-foreground"> · FY{doc.fiscal_year}</span>
          ) : null}
          {doc.filing_date ? (
            <span className="text-muted-foreground/70">
              {" "}
              · {formatShortDate(doc.filing_date)}
            </span>
          ) : null}
        </button>
        <span
          className="hidden shrink-0 text-[10px] text-muted-foreground group-hover:inline"
          title={`${doc.sections_count ?? 0} sections, ${doc.chunks_count ?? 0} chunks`}
        >
          {doc.sections_count ?? 0}§
        </span>
      </div>
    );
  }

  return null;
}

// ---------------------------------------------------------------------
// Context menu
// ---------------------------------------------------------------------
function ContextMenu({
  state,
  onClose,
  onInspect,
  onReindex,
  onDelete,
}: {
  state: ContextMenuState;
  onClose: () => void;
  onInspect: () => void;
  onReindex: () => void;
  onDelete: () => void;
}) {
  const count = state.selectionIds.length;
  const suffix = count > 1 ? ` (${count})` : "";

  return (
    <div
      role="menu"
      onClick={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.preventDefault()}
      className="fixed z-50 min-w-[180px] overflow-hidden rounded-md border border-border bg-popover py-1 text-xs shadow-lg"
      style={{ left: state.x, top: state.y }}
    >
      <MenuButton
        icon={<Eye className="h-3.5 w-3.5" />}
        label="Inspect"
        disabled={count > 1}
        onClick={onInspect}
        hint={count > 1 ? "Inspect works on a single filing" : "→ right panel"}
      />
      <MenuButton
        icon={<RefreshCw className="h-3.5 w-3.5" />}
        label={`Re-index${suffix}`}
        onClick={onReindex}
        hint="re-runs the ingestion pipeline"
      />
      <div className="my-1 border-t border-border/60" />
      <MenuButton
        icon={<Trash2 className="h-3.5 w-3.5" />}
        label={`Delete${suffix}`}
        onClick={onDelete}
        destructive
        hint="drops chunks + evidence cache"
      />
    </div>
  );
}

function MenuButton({
  icon,
  label,
  hint,
  onClick,
  destructive,
  disabled,
}: {
  icon: React.ReactNode;
  label: string;
  hint?: string;
  onClick: () => void;
  destructive?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        destructive
          ? "text-destructive hover:bg-destructive/10"
          : "text-foreground hover:bg-muted",
      )}
    >
      <span className={cn("shrink-0", destructive ? "text-destructive" : "text-muted-foreground")}>
        {icon}
      </span>
      <span className="flex-1 truncate font-medium">{label}</span>
      {hint ? (
        <span className="text-[10px] text-muted-foreground/60">{hint}</span>
      ) : null}
    </button>
  );
}

// ---------------------------------------------------------------------
// Tree builder
// ---------------------------------------------------------------------
function buildTree(documents: DocumentOut[]): TreeNode[] {
  const tickerGroups = new Map<string, DocumentOut[]>();
  for (const doc of documents) {
    const key = doc.ticker || "(unknown)";
    if (!tickerGroups.has(key)) tickerGroups.set(key, []);
    tickerGroups.get(key)!.push(doc);
  }

  return Array.from(tickerGroups.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([ticker, docs]) => {
      const sortedDocs = [...docs].sort(compareDocuments);
      return {
        id: `ticker:${ticker}`,
        kind: "folder" as const,
        label: ticker,
        children: sortedDocs.map((doc) => ({
          id: `doc:${doc.id}`,
          kind: "indexed" as const,
          label: `${doc.document_type}${doc.fiscal_year ? ` FY${doc.fiscal_year}` : ""}`,
          document: doc,
        })),
      };
    });
}

function compareDocuments(a: DocumentOut, b: DocumentOut): number {
  const ya = a.fiscal_year ?? -1;
  const yb = b.fiscal_year ?? -1;
  if (ya !== yb) return yb - ya;
  const da = a.filing_date ?? "";
  const db = b.filing_date ?? "";
  if (da !== db) return db.localeCompare(da);
  return a.document_type.localeCompare(b.document_type);
}

function collectFolderIds(nodes: TreeNode[]): Set<string> {
  const out = new Set<string>();
  const walk = (list: TreeNode[]) => {
    for (const n of list) {
      if (n.kind === "folder") {
        out.add(n.id);
        if (n.children) walk(n.children);
      }
    }
  };
  walk(nodes);
  return out;
}

function collectVisibleIndexedIds(
  nodes: TreeNode[],
  expanded: Set<string>,
): number[] {
  const out: number[] = [];
  const walk = (list: TreeNode[]) => {
    for (const n of list) {
      if (n.kind === "indexed" && n.document) out.push(n.document.id);
      if (n.kind === "folder" && expanded.has(n.id) && n.children) walk(n.children);
    }
  };
  walk(nodes);
  return out;
}

function summarizeFolder(node: TreeNode): { label: string | null } {
  if (!node.children) return { label: null };
  const indexed = countLeaves(node, "indexed");
  if (indexed === 0) return { label: null };
  return { label: `${indexed}` };
}

function countLeaves(node: TreeNode, kind: NodeKind): number {
  if (node.kind === kind) return 1;
  if (!node.children) return 0;
  return node.children.reduce((sum, child) => sum + countLeaves(child, kind), 0);
}

function formatShortDate(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// ---------------------------------------------------------------------
// Range + marquee helpers
// ---------------------------------------------------------------------
interface MarqueeRect {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

function normalizeRect(x0: number, y0: number, x1: number, y1: number) {
  return {
    left: Math.min(x0, x1),
    top: Math.min(y0, y1),
    right: Math.max(x0, x1),
    bottom: Math.max(y0, y1),
  };
}

function idsInRange(order: number[], a: number, b: number): number[] {
  const ia = order.indexOf(a);
  const ib = order.indexOf(b);
  if (ia === -1 || ib === -1) return [b];
  const [lo, hi] = ia < ib ? [ia, ib] : [ib, ia];
  return order.slice(lo, hi + 1);
}

function collectIntersectingDocIds(rect: {
  left: number;
  top: number;
  right: number;
  bottom: number;
}): number[] {
  const out: number[] = [];
  const rows = document.querySelectorAll<HTMLElement>("[data-tree-row][data-doc-id]");
  rows.forEach((row) => {
    const r = row.getBoundingClientRect();
    const intersects =
      r.left < rect.right &&
      r.right > rect.left &&
      r.top < rect.bottom &&
      r.bottom > rect.top;
    if (intersects) {
      const id = Number(row.getAttribute("data-doc-id"));
      if (!Number.isNaN(id)) out.push(id);
    }
  });
  return out;
}
