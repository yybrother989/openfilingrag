"""Docling-based ingestion adapter.

Replaces the previous hand-rolled stack (PyMuPDF/pdfplumber + BeautifulSoup
+ regex section splitter + paragraph chunker + pdfplumber tables) with
Docling's :class:`DocumentConverter` and :class:`HybridChunker`.

Output shape is preserved: a tuple of
``(sections, chunks, tables, page_count)`` consumed unchanged by
:mod:`app.ingestion.pipeline`.

Two paths:
  * **Docling path** for PDF / HTML / DOCX / MD: layout-aware parsing
    with TableFormer table recognition; chunks inherit a hierarchical
    heading path mapped to a SEC canonical section.
  * **Plain-text fallback** for .txt: regex section detection from
    :mod:`app.ingestion.sec_sections` plus paragraph-aware chunking.
    Used when there's no document structure to lean on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import UnsupportedFormatError
from app.core.logging import get_logger
from app.schemas.document import CanonicalSection

from .sec_sections import find_section_breaks, match_canonical_section
from .types import Chunk, DetectedSection, ExtractedTable

log = get_logger(__name__)


_DOCLING_SUFFIXES = {".pdf", ".html", ".htm", ".docx", ".md"}
_TEXT_SUFFIXES = {".txt"}

# Approximate token-per-char ratio for English prose; only used by the
# plain-text fallback. Real chunking uses HybridChunker token counting.
_CHARS_PER_TOKEN = 4.0


@dataclass
class IngestionArtifacts:
    sections: list[DetectedSection]
    chunks: list[Chunk]
    tables: list[ExtractedTable]
    page_count: int


class DoclingIngestor:
    """Adapter that produces our internal section/chunk/table tuples
    from any supported file format.

    The Docling DocumentConverter is created lazily because it pulls
    layout/table models on first use; tests in mock mode avoid that
    cost by going through the plain-text fallback.
    """

    def __init__(
        self,
        max_tokens: int = 700,
        plain_text_target_tokens: int = 700,
        plain_text_overlap_tokens: int = 80,
        plain_text_max_tokens: int = 1100,
    ) -> None:
        self.max_tokens = max_tokens
        self._plain_target_chars = int(plain_text_target_tokens * _CHARS_PER_TOKEN)
        self._plain_overlap_chars = int(plain_text_overlap_tokens * _CHARS_PER_TOKEN)
        self._plain_max_chars = int(plain_text_max_tokens * _CHARS_PER_TOKEN)
        self._converter = None  # built on demand
        self._chunker = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def ingest_file(self, path: str | Path) -> IngestionArtifacts:
        p = Path(path)
        ext = p.suffix.lower()
        if ext in _DOCLING_SUFFIXES:
            return self._ingest_with_docling(p)
        if ext in _TEXT_SUFFIXES:
            return self._ingest_plain_text(p)
        raise UnsupportedFormatError(f"unsupported file type: {ext or '<none>'}")

    # ------------------------------------------------------------------
    # Docling path
    # ------------------------------------------------------------------
    def _ensure_docling(self) -> None:
        if self._converter is not None and self._chunker is not None:
            return
        from docling.document_converter import DocumentConverter
        from docling_core.transforms.chunker.hybrid_chunker import HybridChunker

        self._converter = DocumentConverter()
        self._chunker = HybridChunker(max_tokens=self.max_tokens)

    def _ingest_with_docling(self, path: Path) -> IngestionArtifacts:
        self._ensure_docling()
        log.info("docling convert start", path=str(path))
        result = self._converter.convert(str(path))  # type: ignore[union-attr]
        doc = result.document
        page_count = self._page_count(doc)

        # Chunk via HybridChunker — yields DocChunk with .text and .meta
        raw_chunks = list(self._chunker.chunk(doc))  # type: ignore[union-attr]
        log.info("docling chunked", chunks=len(raw_chunks))

        # Build sections (deduped by canonical name in document order) and
        # chunks (preserve order, attach page span + section).
        chunks: list[Chunk] = []
        sections_by_canonical: dict[str, DetectedSection] = {}
        running_offset = 0  # synthetic char offset for parity with old shape

        for idx, ch in enumerate(raw_chunks):
            text = (getattr(ch, "text", None) or "").strip()
            if not text:
                continue
            headings = list(getattr(ch.meta, "headings", []) or [])
            doc_items = list(getattr(ch.meta, "doc_items", []) or [])
            page_start, page_end = _page_span(doc_items)
            canonical, raw_heading = self._canonical_for_headings(headings)

            char_start = running_offset
            char_end = running_offset + len(text)
            running_offset = char_end + 2  # tiny gap so spans don't overlap

            chunks.append(
                Chunk(
                    section_canonical=canonical,
                    raw_heading=raw_heading,
                    chunk_text=text,
                    chunk_index=idx,
                    char_start=char_start,
                    char_end=char_end,
                    page_start=page_start,
                    page_end=page_end,
                )
            )

            sec = sections_by_canonical.get(canonical)
            if sec is None:
                sections_by_canonical[canonical] = DetectedSection(
                    canonical_name=canonical,
                    raw_heading=raw_heading or "",
                    char_start=char_start,
                    char_end=char_end,
                    page_start=page_start,
                    page_end=page_end,
                    text=text,
                    ordinal=len(sections_by_canonical),
                )
            else:
                sec.char_end = char_end
                if page_end is not None:
                    sec.page_end = page_end
                sec.text = (sec.text + "\n\n" + text) if sec.text else text

        sections = list(sections_by_canonical.values())
        sections.sort(key=lambda s: s.char_start)
        for i, sec in enumerate(sections):
            sec.ordinal = i

        tables = self._extract_tables(doc, sections)

        return IngestionArtifacts(
            sections=sections,
            chunks=chunks,
            tables=tables,
            page_count=page_count,
        )

    @staticmethod
    def _canonical_for_headings(headings: list[str]) -> tuple[str, str | None]:
        for h in headings:
            matched = match_canonical_section(h)
            if matched is not None:
                return matched.value, h
        # No SEC heading matched — bucket into Other but preserve the raw
        # heading path so the chunk metadata still tells you where it
        # lives in the document.
        raw = " > ".join(headings) if headings else None
        return CanonicalSection.OTHER.value, raw

    @staticmethod
    def _page_count(doc) -> int:
        # DoclingDocument exposes pages as a dict in newer versions and
        # as an attribute in older ones; both contain entries keyed by
        # 1-based page number.
        pages = getattr(doc, "pages", None)
        if pages is None:
            return 0
        try:
            return len(pages)
        except TypeError:
            return 0

    @staticmethod
    def _extract_tables(doc, sections: list[DetectedSection]) -> list[ExtractedTable]:
        out: list[ExtractedTable] = []
        tables = getattr(doc, "tables", None) or []
        # Build a quick page → canonical lookup so tables get bucketed
        # into the section containing their page.
        section_for_page: dict[int, str] = {}
        for sec in sections:
            if sec.page_start is None:
                continue
            for p in range(sec.page_start, (sec.page_end or sec.page_start) + 1):
                section_for_page.setdefault(p, sec.canonical_name)

        for tbl in tables:
            page = _first_page(getattr(tbl, "prov", None))
            rows = _table_rows(tbl)
            if not rows:
                continue
            out.append(
                ExtractedTable(
                    page=page or 0,
                    rows=rows,
                    caption=getattr(tbl, "caption", None) or None,
                    section_canonical=section_for_page.get(page) if page else None,
                )
            )
        return out

    # ------------------------------------------------------------------
    # Plain-text fallback path
    # ------------------------------------------------------------------
    def _ingest_plain_text(self, path: Path) -> IngestionArtifacts:
        text = path.read_text(encoding="utf-8", errors="ignore")
        sections = self._split_text_into_sections(text)
        chunks = self._chunk_plain_sections(sections)
        return IngestionArtifacts(
            sections=sections,
            chunks=chunks,
            tables=[],
            page_count=1,
        )

    def _split_text_into_sections(self, full_text: str) -> list[DetectedSection]:
        breaks = find_section_breaks(full_text)
        sections: list[DetectedSection] = []
        if not breaks:
            sections.append(
                DetectedSection(
                    canonical_name=CanonicalSection.OTHER.value,
                    raw_heading="",
                    char_start=0,
                    char_end=len(full_text),
                    text=full_text,
                    page_start=1,
                    page_end=1,
                    ordinal=0,
                )
            )
            return sections

        first_start = breaks[0][0]
        if first_start > 20:
            sections.append(
                DetectedSection(
                    canonical_name=CanonicalSection.OTHER.value,
                    raw_heading="",
                    char_start=0,
                    char_end=first_start,
                    text=full_text[:first_start],
                    page_start=1,
                    page_end=1,
                    ordinal=0,
                )
            )

        for i, (start, _heading_end, canonical, heading) in enumerate(breaks):
            next_start = breaks[i + 1][0] if i + 1 < len(breaks) else len(full_text)
            chunk_text = full_text[start:next_start]
            if len(chunk_text) < 20:
                continue
            sections.append(
                DetectedSection(
                    canonical_name=canonical.value,
                    raw_heading=heading,
                    char_start=start,
                    char_end=next_start,
                    text=chunk_text,
                    page_start=1,
                    page_end=1,
                    ordinal=len(sections),
                )
            )

        for i, sec in enumerate(sections):
            sec.ordinal = i
        return sections

    def _chunk_plain_sections(self, sections: list[DetectedSection]) -> list[Chunk]:
        chunks: list[Chunk] = []
        idx = 0
        for sec in sections:
            for piece in self._chunk_single_section(sec):
                piece.chunk_index = idx
                chunks.append(piece)
                idx += 1
        return chunks

    def _chunk_single_section(self, sec: DetectedSection) -> list[Chunk]:
        text = sec.text
        if not text.strip():
            return []
        paragraphs = re.split(r"\n\s*\n", text)
        out: list[Chunk] = []
        buf: list[str] = []
        buf_len = 0

        def flush() -> None:
            nonlocal buf, buf_len
            if not buf:
                return
            chunk_text = "\n\n".join(buf).strip()
            if not chunk_text:
                buf, buf_len = [], 0
                return
            local_start = text.find(chunk_text)
            if local_start < 0:
                local_start = 0
            abs_start = sec.char_start + local_start
            abs_end = abs_start + len(chunk_text)
            out.append(
                Chunk(
                    section_canonical=sec.canonical_name,
                    raw_heading=sec.raw_heading or None,
                    chunk_text=chunk_text,
                    chunk_index=0,  # fixed up by caller
                    char_start=abs_start,
                    char_end=abs_end,
                    page_start=sec.page_start,
                    page_end=sec.page_end,
                )
            )
            if self._plain_overlap_chars > 0 and len(chunk_text) > self._plain_overlap_chars:
                tail = chunk_text[-self._plain_overlap_chars :]
                buf = [tail]
                buf_len = len(tail)
            else:
                buf, buf_len = [], 0

        for para in paragraphs:
            p = para.strip()
            if not p:
                continue
            if len(p) > self._plain_max_chars:
                step = max(self._plain_target_chars - self._plain_overlap_chars, 1)
                for slice_start in range(0, len(p), step):
                    sub = p[slice_start : slice_start + self._plain_target_chars]
                    if buf_len + len(sub) > self._plain_target_chars and buf:
                        flush()
                    buf.append(sub)
                    buf_len += len(sub)
                    if buf_len >= self._plain_target_chars:
                        flush()
                continue
            if buf_len + len(p) > self._plain_target_chars and buf:
                flush()
            buf.append(p)
            buf_len += len(p)
            if buf_len >= self._plain_target_chars:
                flush()

        flush()
        return out


def _page_span(doc_items: list) -> tuple[int | None, int | None]:
    pages: list[int] = []
    for item in doc_items:
        for prov in getattr(item, "prov", []) or []:
            page_no = getattr(prov, "page_no", None)
            if isinstance(page_no, int):
                pages.append(page_no)
    if not pages:
        return None, None
    return min(pages), max(pages)


def _first_page(prov) -> int | None:
    if not prov:
        return None
    for p in prov:
        page_no = getattr(p, "page_no", None)
        if isinstance(page_no, int):
            return page_no
    return None


def _table_rows(tbl) -> list[list[str]]:
    """Best-effort row extraction from a Docling TableItem.

    Newer Docling versions expose ``data.grid`` as a 2-D list of
    ``TableCell``; older ones expose ``rows`` directly. We accept either.
    """
    data = getattr(tbl, "data", None)
    grid = getattr(data, "grid", None) if data is not None else None
    if grid:
        return [[(getattr(cell, "text", "") or "").strip() for cell in row] for row in grid]
    rows = getattr(tbl, "rows", None)
    if rows:
        out: list[list[str]] = []
        for row in rows:
            out.append([(getattr(cell, "text", str(cell)) or "").strip() for cell in row])
        return out
    return []
