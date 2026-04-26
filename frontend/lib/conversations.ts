"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Multi-conversation persistence layer.
 *
 * Storage layout:
 *   openfilingrag.conversations.v1   → ConversationMeta[] (newest first)
 *   openfilingrag.current-conv.v1    → string (active id)
 *   openfilingrag.thread.{id}        → ExportedMessageRepository for that
 *                                       conversation, written by the runtime
 *                                       in assistantRuntime.tsx
 *
 * The runtime takes `conversationId` and uses it to scope its history
 * storage key — switching conversations remounts the Thread (via
 * `key={conversationId}`) so React tears down state cleanly.
 */

export interface ConversationMeta {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
}

const INDEX_KEY = "openfilingrag.conversations.v1";
const CURRENT_KEY = "openfilingrag.current-conv.v1";
export const THREAD_KEY_PREFIX = "openfilingrag.thread.";

const DEFAULT_TITLE = "New conversation";

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `c-${Math.random().toString(36).slice(2)}-${Date.now()}`;
}

function readIndex(): ConversationMeta[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(INDEX_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ConversationMeta[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeIndex(list: ConversationMeta[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(INDEX_KEY, JSON.stringify(list));
}

function readCurrent(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(CURRENT_KEY);
}

function writeCurrent(id: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(CURRENT_KEY, id);
}

export function useConversations() {
  const [conversations, setConversations] = useState<ConversationMeta[]>([]);
  // Initialize lazily on mount so SSR/CSR don't diverge on the random id.
  const [currentId, setCurrentId] = useState<string>("");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const list = readIndex();
    const stored = readCurrent();
    if (list.length === 0) {
      // First run: create a default conversation
      const meta: ConversationMeta = {
        id: newId(),
        title: DEFAULT_TITLE,
        createdAt: Date.now(),
        updatedAt: Date.now(),
      };
      setConversations([meta]);
      setCurrentId(meta.id);
      writeIndex([meta]);
      writeCurrent(meta.id);
    } else {
      setConversations(list);
      const target = stored && list.some((c) => c.id === stored) ? stored : list[0].id;
      setCurrentId(target);
      writeCurrent(target);
    }
    setHydrated(true);
  }, []);

  const newConversation = useCallback(() => {
    const meta: ConversationMeta = {
      id: newId(),
      title: DEFAULT_TITLE,
      createdAt: Date.now(),
      updatedAt: Date.now(),
    };
    setConversations((current) => {
      const next = [meta, ...current];
      writeIndex(next);
      return next;
    });
    setCurrentId(meta.id);
    writeCurrent(meta.id);
  }, []);

  const switchTo = useCallback((id: string) => {
    setCurrentId(id);
    writeCurrent(id);
  }, []);

  const deleteConversation = useCallback(
    (id: string) => {
      setConversations((current) => {
        const next = current.filter((c) => c.id !== id);
        writeIndex(next);
        // Drop the per-thread storage too.
        if (typeof window !== "undefined") {
          window.localStorage.removeItem(THREAD_KEY_PREFIX + id);
        }
        // If we deleted the active one, switch to the next available
        // (or create a fresh one if the list is now empty).
        if (id === currentId) {
          if (next.length > 0) {
            setCurrentId(next[0].id);
            writeCurrent(next[0].id);
          } else {
            const meta: ConversationMeta = {
              id: newId(),
              title: DEFAULT_TITLE,
              createdAt: Date.now(),
              updatedAt: Date.now(),
            };
            const seeded = [meta];
            writeIndex(seeded);
            setCurrentId(meta.id);
            writeCurrent(meta.id);
            return seeded;
          }
        }
        return next;
      });
    },
    [currentId],
  );

  /**
   * Called by the runtime when a user message lands. We promote the
   * conversation to the top of the index and, if the title is still
   * the placeholder, set it from the prompt.
   */
  const touchConversation = useCallback(
    (id: string, candidateTitle?: string) => {
      setConversations((current) => {
        const idx = current.findIndex((c) => c.id === id);
        if (idx === -1) return current;
        const updated: ConversationMeta = {
          ...current[idx],
          updatedAt: Date.now(),
          title:
            current[idx].title === DEFAULT_TITLE && candidateTitle
              ? truncateTitle(candidateTitle)
              : current[idx].title,
        };
        const next = [updated, ...current.filter((_, i) => i !== idx)];
        writeIndex(next);
        return next;
      });
    },
    [],
  );

  return {
    conversations,
    currentId,
    hydrated,
    newConversation,
    switchTo,
    deleteConversation,
    touchConversation,
  };
}

function truncateTitle(text: string): string {
  const clean = text.trim().replace(/\s+/g, " ");
  if (clean.length <= 48) return clean;
  return clean.slice(0, 47) + "…";
}
