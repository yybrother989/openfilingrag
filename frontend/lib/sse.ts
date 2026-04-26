/**
 * Spec-correct SSE frame parser used by both the assistant runtime and the
 * legacy stream adapter. Handles:
 *
 * - Frame delimiter normalization: SSE allows `\n\n`, `\r\n\r\n`, or `\r\r`.
 *   We normalize CRLF/CR to LF before scanning.
 * - Multi-line `data:` fields: each `data:` line is appended; lines are
 *   joined with `\n` per spec (https://html.spec.whatwg.org/#parsing-an-event-stream).
 * - Optional single space after the colon: `data:hello` and `data: hello`
 *   both yield `hello`.
 *
 * `framesFromBuffer` returns complete frames from a rolling buffer and the
 * remaining tail (which may contain a partial frame).
 */

export function framesFromBuffer(raw: string): { frames: string[]; rest: string } {
  // Normalize line endings once. The WHATWG event-stream parser treats
  // any of \n, \r, or \r\n as a line terminator.
  const buffer = raw.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const frames: string[] = [];
  let start = 0;
  let idx = buffer.indexOf("\n\n", start);
  while (idx !== -1) {
    frames.push(buffer.slice(start, idx));
    start = idx + 2;
    idx = buffer.indexOf("\n\n", start);
  }
  return { frames, rest: buffer.slice(start) };
}

/**
 * Read an HTTP response body for inclusion in an error message.
 * Handles JSON `{detail: "..."}` (FastAPI's convention) and trims oversized
 * bodies so a 500 with a stack trace doesn't blow up the UI.
 */
export async function readErrorBody(response: Response): Promise<string> {
  try {
    const text = (await response.text()).trim();
    if (!text) return "";
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (typeof parsed.detail === "string") return parsed.detail;
    } catch {
      // not JSON — fall through and return the raw text
    }
    return text.length > 500 ? `${text.slice(0, 500)}...` : text;
  } catch {
    return "";
  }
}

export function parseSSEFrame<T = unknown>(frame: string): T | null {
  const dataLines: string[] = [];
  for (const rawLine of frame.split("\n")) {
    // raw frame is already LF-normalized by framesFromBuffer, but be
    // defensive in case a caller passes something else.
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (line.startsWith(":")) continue; // comment
    if (!line.startsWith("data:")) continue;
    const value = line.slice(5);
    dataLines.push(value.startsWith(" ") ? value.slice(1) : value);
  }
  if (dataLines.length === 0) return null;
  try {
    return JSON.parse(dataLines.join("\n")) as T;
  } catch {
    return null;
  }
}
