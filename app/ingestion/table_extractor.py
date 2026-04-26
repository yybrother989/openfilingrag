"""Financial table extraction using pdfplumber.

Best-effort: pdfplumber's table heuristics are good but not perfect on
complex SEC layouts. Returns one :class:`ExtractedTable` per detected
table with the raw rows preserved as a list-of-lists.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class ExtractedTable:
    page: int
    rows: list[list[str]]
    caption: str | None = None
    section_canonical: str | None = None


class TableExtractor:
    """Extract tables from PDFs using pdfplumber."""

    def extract(self, path: str | Path) -> list[ExtractedTable]:
        try:
            import pdfplumber
        except ImportError:
            log.warning("pdfplumber not installed — skipping table extraction")
            return []

        path = Path(path)
        if not path.exists():
            return []

        out: list[ExtractedTable] = []
        try:
            with pdfplumber.open(str(path)) as pdf:
                for page_idx, page in enumerate(pdf.pages, start=1):
                    try:
                        tables = page.extract_tables() or []
                    except Exception as e:
                        log.debug("table extraction error", page=page_idx, err=str(e))
                        continue
                    for tbl in tables:
                        cleaned = [
                            [(cell or "").strip() for cell in row]
                            for row in tbl
                            if any((cell or "").strip() for cell in row)
                        ]
                        if not cleaned or len(cleaned) < 2:
                            continue
                        out.append(ExtractedTable(page=page_idx, rows=cleaned))
        except Exception as e:
            log.warning("pdfplumber failed", path=str(path), err=str(e))

        return out
