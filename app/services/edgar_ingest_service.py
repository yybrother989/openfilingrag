"""Pull SEC EDGAR filings and ingest them via the existing pipeline.

Reuses :class:`app.ingestion.pipeline.IngestionPipeline` — no parser
changes needed, since EDGAR primary documents are HTML which the existing
``HTMLParser`` already handles. Dedupes against ``documents.source_url``
so re-running ``edgar-pull`` is idempotent.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.data_sources.sec_edgar import (
    DEFAULT_FORM_TYPES,
    FilingRef,
    SECEdgarClient,
)
from app.db.models import Document
from app.ingestion.pipeline import IngestionPipeline
from app.schemas.document import (
    DocumentMetadata,
    DocumentType,
    IngestionResult,
    SourcePriority,
)

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings

log = get_logger(__name__)


FORM_TO_DOC_TYPE: dict[str, DocumentType] = {
    "10-K": DocumentType.TEN_K,
    "10-K/A": DocumentType.TEN_K,
    "10-Q": DocumentType.TEN_Q,
    "10-Q/A": DocumentType.TEN_Q,
    "8-K": DocumentType.EIGHT_K,
    "8-K/A": DocumentType.EIGHT_K,
}


@dataclass
class EdgarPullSummary:
    ticker: str
    cik: int | None
    listed: int
    downloaded: int
    ingested: int
    skipped_existing: int
    failures: int
    results: list[IngestionResult]


class EdgarIngestService:
    """Resolve ticker → list filings → download → ingest."""

    def __init__(
        self,
        embeddings: "Embeddings",
        edgar_client: SECEdgarClient | None = None,
        pipeline: IngestionPipeline | None = None,
        filings_dir: Path | None = None,
    ) -> None:
        self.embeddings = embeddings
        self.edgar = edgar_client or SECEdgarClient()
        self.pipeline = pipeline or IngestionPipeline(embeddings=embeddings)
        self.filings_dir = filings_dir or Path(settings.sec_edgar_filings_dir)

    # ------------------------------------------------------------------
    def list_filings(
        self,
        ticker: str,
        types: Iterable[str] = DEFAULT_FORM_TYPES,
        limit: int = 10,
        since: date | None = None,
    ) -> list[FilingRef]:
        return self.edgar.list_filings(ticker, tuple(types), limit=limit, since=since)

    # ------------------------------------------------------------------
    def pull_and_ingest(
        self,
        ticker: str,
        session: Session,
        types: Iterable[str] = DEFAULT_FORM_TYPES,
        limit: int = 3,
        since: date | None = None,
        company_name: str | None = None,
    ) -> EdgarPullSummary:
        ticker = ticker.upper().strip()
        cik = self.edgar.resolve_cik(ticker)
        refs = self.edgar.list_filings(ticker, tuple(types), limit=limit, since=since)
        log.info("edgar list", ticker=ticker, cik=cik, count=len(refs))

        downloaded = 0
        ingested = 0
        skipped = 0
        failures = 0
        results: list[IngestionResult] = []

        for ref in refs:
            if self._already_ingested(session, ref):
                skipped += 1
                log.info("filing already ingested, skipping", url=ref.archive_url)
                continue

            try:
                local_path = self.edgar.download_filing(ref, self.filings_dir)
                downloaded += 1
            except Exception as e:
                failures += 1
                log.warning("download failed", err=str(e), accession=ref.accession_number)
                continue

            meta = self._build_metadata(ref, company_name=company_name)
            try:
                result = self.pipeline.ingest(local_path, meta, session)
                session.flush()  # let dedupe see it within the same session
                ingested += 1
                results.append(result)
            except Exception as e:
                failures += 1
                session.rollback()
                log.warning("ingest failed", err=str(e), accession=ref.accession_number)
                continue

        if ingested:
            session.commit()

        return EdgarPullSummary(
            ticker=ticker,
            cik=cik,
            listed=len(refs),
            downloaded=downloaded,
            ingested=ingested,
            skipped_existing=skipped,
            failures=failures,
            results=results,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _already_ingested(session: Session, ref: FilingRef) -> bool:
        existing = session.scalar(
            select(Document.id).where(Document.source_url == ref.archive_url).limit(1)
        )
        return existing is not None

    @staticmethod
    def _build_metadata(ref: FilingRef, company_name: str | None) -> DocumentMetadata:
        doc_type = FORM_TO_DOC_TYPE.get(ref.form, DocumentType.OTHER)
        return DocumentMetadata(
            ticker=ref.ticker,
            company_name=company_name or ref.ticker,
            document_type=doc_type,
            fiscal_year=ref.fiscal_year,
            filing_date=ref.filing_date,
            source_url=ref.archive_url,
            source_priority=SourcePriority.PRIMARY_FILING,
        )
