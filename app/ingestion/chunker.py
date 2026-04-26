"""Section-aware chunker.

Splits each section into ~target_tokens-sized chunks with a small overlap
so retrieval cleanly hits boundary text. Each chunk inherits its section
name, page span, and ordinal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .section_splitter import DetectedSection

# Approximate token-per-char ratio for English prose without a tokenizer.
# Good enough for chunking — exact LLM token counts happen at embed-time.
_CHARS_PER_TOKEN = 4.0


@dataclass
class Chunk:
    section_canonical: str
    raw_heading: str | None
    chunk_text: str
    chunk_index: int
    char_start: int  # absolute offset in full_text
    char_end: int
    page_start: int | None
    page_end: int | None


class Chunker:
    def __init__(
        self,
        target_tokens: int = 700,
        overlap_tokens: int = 80,
        max_tokens: int = 1100,
    ) -> None:
        self.target_chars = int(target_tokens * _CHARS_PER_TOKEN)
        self.overlap_chars = int(overlap_tokens * _CHARS_PER_TOKEN)
        self.max_chars = int(max_tokens * _CHARS_PER_TOKEN)

    def chunk_sections(
        self,
        sections: list[DetectedSection],
        char_to_page: list[int] | None = None,
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        global_idx = 0
        for sec in sections:
            for c in self._chunk_section(sec, global_idx, char_to_page):
                chunks.append(c)
                global_idx += 1
        return chunks

    def _chunk_section(
        self,
        sec: DetectedSection,
        start_idx: int,
        char_to_page: list[int] | None,
    ) -> list[Chunk]:
        text = sec.text
        if not text.strip():
            return []

        # Split on paragraph boundaries first to keep chunk edges clean.
        paragraphs = re.split(r"\n\s*\n", text)
        out: list[Chunk] = []
        buf: list[str] = []
        buf_len = 0
        idx = start_idx

        def flush() -> None:
            nonlocal buf, buf_len, idx
            if not buf:
                return
            chunk_text = "\n\n".join(buf).strip()
            if not chunk_text:
                buf, buf_len = [], 0
                return
            # Reconstruct absolute char span by searching within section text
            local_start = text.find(chunk_text)
            if local_start < 0:
                local_start = 0
            abs_start = sec.char_start + local_start
            abs_end = abs_start + len(chunk_text)
            page_start = _page_at(char_to_page, abs_start) or sec.page_start
            page_end = _page_at(char_to_page, max(abs_end - 1, abs_start)) or sec.page_end
            out.append(
                Chunk(
                    section_canonical=sec.canonical_name,
                    raw_heading=sec.raw_heading or None,
                    chunk_text=chunk_text,
                    chunk_index=idx,
                    char_start=abs_start,
                    char_end=abs_end,
                    page_start=page_start,
                    page_end=page_end,
                )
            )
            idx += 1
            # Overlap: keep the trailing N chars from this chunk in the buffer
            if self.overlap_chars > 0 and len(chunk_text) > self.overlap_chars:
                tail = chunk_text[-self.overlap_chars :]
                buf = [tail]
                buf_len = len(tail)
            else:
                buf, buf_len = [], 0

        for para in paragraphs:
            p = para.strip()
            if not p:
                continue
            # Hard cap: if a single paragraph exceeds max_chars, split it
            if len(p) > self.max_chars:
                for slice_start in range(0, len(p), self.target_chars - self.overlap_chars):
                    sub = p[slice_start : slice_start + self.target_chars]
                    if buf_len + len(sub) > self.target_chars and buf:
                        flush()
                    buf.append(sub)
                    buf_len += len(sub)
                    if buf_len >= self.target_chars:
                        flush()
                continue
            if buf_len + len(p) > self.target_chars and buf:
                flush()
            buf.append(p)
            buf_len += len(p)
            if buf_len >= self.target_chars:
                flush()

        flush()
        return out


def _page_at(char_to_page: list[int] | None, idx: int) -> int | None:
    if not char_to_page:
        return None
    if idx < 0 or idx >= len(char_to_page):
        return None
    return char_to_page[idx]
