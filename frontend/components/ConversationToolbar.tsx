"use client";

import { useEffect, useRef, useState } from "react";
import { History, MessageSquarePlus, Trash2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ConversationMeta } from "@/lib/conversations";

interface Props {
  conversations: ConversationMeta[];
  currentId: string;
  onNew: () => void;
  onSwitch: (id: string) => void;
  onDelete: (id: string) => void;
}

/**
 * Two icon buttons that float above the chat thread:
 *   • History — popover listing all conversations, click to switch
 *   • New     — start a fresh thread
 *
 * Persistence happens in the conversations hook (localStorage).
 */
export function ConversationToolbar({
  conversations,
  currentId,
  onNew,
  onSwitch,
  onDelete,
}: Props) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on outside click / escape
  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="relative flex items-center gap-1">
      <IconButton
        title="Conversation history"
        onClick={() => setOpen((v) => !v)}
        active={open}
      >
        <History className="h-4 w-4" />
      </IconButton>
      <IconButton
        title="New conversation"
        onClick={() => {
          setOpen(false);
          onNew();
        }}
      >
        <MessageSquarePlus className="h-4 w-4" />
      </IconButton>

      {open ? (
        <div className="absolute right-0 top-full z-30 mt-1 w-72 overflow-hidden rounded-md border border-border bg-popover shadow-lg">
          <div className="flex items-center justify-between border-b border-border/60 px-3 py-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              History
            </span>
            <span className="text-[10px] text-muted-foreground/70">
              {conversations.length}
            </span>
          </div>
          {conversations.length === 0 ? (
            <div className="px-3 py-3 text-[11px] text-muted-foreground">
              No saved conversations yet.
            </div>
          ) : (
            <ul className="max-h-80 overflow-y-auto py-1">
              {conversations.map((c) => {
                const active = c.id === currentId;
                return (
                  <li
                    key={c.id}
                    className={cn(
                      "group flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-muted/50",
                      active && "bg-primary/5",
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => {
                        onSwitch(c.id);
                        setOpen(false);
                      }}
                      className="min-w-0 flex-1 text-left"
                    >
                      <div className="truncate font-medium text-foreground">
                        {c.title}
                      </div>
                      <div className="text-[10px] text-muted-foreground/70">
                        {formatRelative(c.updatedAt)}
                      </div>
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (window.confirm(`Delete "${c.title}"?`)) {
                          onDelete(c.id);
                        }
                      }}
                      className="invisible shrink-0 rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive group-hover:visible"
                      title="Delete conversation"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}

function IconButton({
  children,
  title,
  active,
  onClick,
}: {
  children: React.ReactNode;
  title: string;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors",
        "hover:bg-muted hover:text-foreground",
        active && "bg-muted text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function formatRelative(timestamp: number): string {
  const diff = Date.now() - timestamp;
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < minute) return "just now";
  if (diff < hour) return `${Math.floor(diff / minute)}m ago`;
  if (diff < day) return `${Math.floor(diff / hour)}h ago`;
  if (diff < 7 * day) return `${Math.floor(diff / day)}d ago`;
  return new Date(timestamp).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}
