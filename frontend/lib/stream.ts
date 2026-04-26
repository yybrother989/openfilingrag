/**
 * SSE stream adapter for /research/stream.
 *
 * The browser's `EventSource` doesn't support POST bodies, so we read the
 * response body manually with `fetch` + `ReadableStream` and parse the SSE
 * frames ourselves. Each frame is dispatched to `onEvent`.
 */

import { framesFromBuffer, parseSSEFrame, readErrorBody } from "./sse";
import type { AgentEvent } from "./types";

export interface StreamRequest {
  query: string;
  ticker?: string;
  company_name?: string;
  fiscal_year?: number | null;
  document_type?: string;
  top_k?: number | null;
}

export interface StreamHandle {
  cancel: () => void;
  done: Promise<void>;
}

export interface StreamCallbacks {
  onEvent: (event: AgentEvent) => void;
  onError?: (err: Error) => void;
  onClose?: () => void;
}

const API_BASE =
  typeof window !== "undefined"
    ? "/api"
    : process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

/** Open a streaming research run and pipe events to callbacks. */
export function streamResearch(
  request: StreamRequest,
  callbacks: StreamCallbacks,
): StreamHandle {
  const controller = new AbortController();

  const done = (async () => {
    let response: Response;
    try {
      response = await fetch(`${API_BASE}/research/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify(request),
        signal: controller.signal,
      });
    } catch (e) {
      if ((e as Error).name === "AbortError") {
        callbacks.onClose?.();
        return;
      }
      callbacks.onError?.(e as Error);
      return;
    }

    if (!response.ok || !response.body) {
      const detail = await readErrorBody(response);
      callbacks.onError?.(
        new Error(
          detail
            ? `stream HTTP ${response.status}: ${detail}`
            : `stream HTTP ${response.status}`,
        ),
      );
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    try {
      while (true) {
        const { done: streamDone, value } = await reader.read();
        if (streamDone) break;
        buffer += decoder.decode(value, { stream: true });
        const { frames, rest } = framesFromBuffer(buffer);
        buffer = rest;
        for (const frame of frames) {
          const evt = parseSSEFrame<AgentEvent>(frame);
          if (evt) callbacks.onEvent(evt);
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        callbacks.onError?.(e as Error);
      }
    } finally {
      callbacks.onClose?.();
    }
  })();

  return {
    cancel: () => controller.abort(),
    done,
  };
}
