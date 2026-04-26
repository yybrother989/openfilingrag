"""PDF parsing — PyMuPDF for text + page numbers, pdfplumber for tables."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import IngestionError
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class ParsedPage:
    page_number: int  # 1-indexed
    text: str


@dataclass
class ParsedDocument:
    pages: list[ParsedPage] = field(default_factory=list)
    full_text: str = ""
    page_count: int = 0
    char_to_page: list[int] = field(default_factory=list)
    """For each character offset in `full_text`, the page number it belongs to.

    Used by the chunker so chunks know which page span they come from.
    """


class PDFParser:
    """Page-aware PDF parser.

    Falls back to plain-text concatenation if PyMuPDF cannot open the file
    (e.g. encrypted or corrupt).
    """

    def parse(self, path: str | Path) -> ParsedDocument:
        try:
            import fitz  # PyMuPDF
        except ImportError as e:
            raise IngestionError(
                "PyMuPDF (fitz) is required for PDF parsing — `pip install pymupdf`"
            ) from e

        path = Path(path)
        if not path.exists():
            raise IngestionError(f"PDF not found: {path}")

        log.info("parsing pdf", path=str(path))
        try:
            doc = fitz.open(str(path))
        except Exception as e:
            raise IngestionError(f"failed to open PDF: {e}") from e

        pages: list[ParsedPage] = []
        char_to_page: list[int] = []
        full_parts: list[str] = []
        char_offset = 0

        for i, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            text = text.strip() + "\n\n"
            pages.append(ParsedPage(page_number=i, text=text))
            full_parts.append(text)
            char_to_page.extend([i] * len(text))
            char_offset += len(text)

        doc.close()
        full_text = "".join(full_parts)
        return ParsedDocument(
            pages=pages,
            full_text=full_text,
            page_count=len(pages),
            char_to_page=char_to_page,
        )
