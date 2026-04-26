"""HTML / plain-text filing parser."""

from __future__ import annotations

from pathlib import Path

from app.core.errors import IngestionError
from app.core.logging import get_logger

from .pdf_parser import ParsedDocument, ParsedPage

log = get_logger(__name__)


class HTMLParser:
    """Strips chrome and returns a single-page :class:`ParsedDocument`.

    HTML filings (e.g. SEC iXBRL exports) don't have intrinsic pages, so
    we synthesize one logical page covering the whole document.
    """

    STRIP_TAGS = {"script", "style", "nav", "footer", "header", "noscript"}

    def parse(self, path: str | Path) -> ParsedDocument:
        try:
            import warnings

            from bs4 import BeautifulSoup

            # iXBRL filings begin with an XML declaration which makes BS4
            # log a noisy XMLParsedAsHTMLWarning. We treat them as HTML on
            # purpose (the markup is HTML with embedded XBRL tags), so
            # suppress the warning here.
            try:
                from bs4 import XMLParsedAsHTMLWarning  # type: ignore[attr-defined]

                warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
            except ImportError:
                pass
        except ImportError as e:
            raise IngestionError(
                "beautifulsoup4 is required for HTML parsing — `pip install beautifulsoup4`"
            ) from e

        path = Path(path)
        if not path.exists():
            raise IngestionError(f"HTML not found: {path}")

        log.info("parsing html", path=str(path))
        raw = path.read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(raw, "lxml")

        for tag in soup(self.STRIP_TAGS):
            tag.decompose()

        text = soup.get_text(separator="\n")
        # Collapse runs of whitespace but keep paragraph breaks
        lines = [ln.strip() for ln in text.splitlines()]
        cleaned = "\n".join(ln for ln in lines if ln)

        return ParsedDocument(
            pages=[ParsedPage(page_number=1, text=cleaned)],
            full_text=cleaned,
            page_count=1,
            char_to_page=[1] * len(cleaned),
        )


class TextParser:
    """Plain-text fallback (treats the whole file as page 1)."""

    def parse(self, path: str | Path) -> ParsedDocument:
        path = Path(path)
        if not path.exists():
            raise IngestionError(f"text file not found: {path}")
        log.info("parsing text", path=str(path))
        text = path.read_text(encoding="utf-8", errors="ignore")
        return ParsedDocument(
            pages=[ParsedPage(page_number=1, text=text)],
            full_text=text,
            page_count=1,
            char_to_page=[1] * len(text),
        )
