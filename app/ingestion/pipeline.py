"""End-to-end ingestion pipeline.

Flow:
  1. Parse + chunk + extract tables in one Docling pass (or plain-text
     fallback for .txt). See :mod:`.docling_adapter`.
  2. Enrich chunks with content_type + metric/risk tags.
  3. Embed + write chunks to PGVector (``langchain_pg_embedding``).
  4. Upsert ``Company`` / ``Document`` / ``DocumentSection`` /
     ``FinancialTable`` rows in the same SQLAlchemy transaction.

Designed to be transactional: a single SQLAlchemy session holds all
non-PGVector writes; PGVector writes happen inside the same code path
(its own engine), so a failure during chunk write rolls back the
SQL-side rows via session rollback. Re-running ingest is idempotent —
deterministic ``source_id`` keeps PGVector upserts stable.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.documents import Document as LCDocument
from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models import Company, Document, DocumentSection, FinancialTable
from app.retrieval.pg_vector_store import build_pg_vector
from app.schemas.document import DocumentMetadata, IngestionResult

from .docling_adapter import DoclingIngestor
from .metadata_enricher import MetadataEnricher
from .source_id import chunk_source_id

if TYPE_CHECKING:
    from langchain_postgres import PGVector
    from sqlalchemy.orm import Session

    from app.services.embedding_service import EmbeddingService

log = get_logger(__name__)


class IngestionPipeline:
    """Orchestrates Docling parsing/chunking → enrichment → PGVector upsert."""

    def __init__(
        self,
        embedding_service: "EmbeddingService",
        ingestor: DoclingIngestor | None = None,
        enricher: MetadataEnricher | None = None,
        vector_store: "PGVector | None" = None,
    ) -> None:
        self.embedding_service = embedding_service
        self.ingestor = ingestor or DoclingIngestor()
        self.enricher = enricher or MetadataEnricher()
        self._vector_store = vector_store

    @property
    def vector_store(self) -> "PGVector":
        if self._vector_store is None:
            self._vector_store = build_pg_vector(self.embedding_service)
        return self._vector_store

    def ingest(
        self,
        file_path: str | Path,
        meta: DocumentMetadata,
        session: "Session",
    ) -> IngestionResult:
        path = Path(file_path)
        log.info(
            "ingest start",
            path=str(path),
            ticker=meta.ticker,
            doc_type=meta.document_type.value,
        )
        warnings: list[str] = []

        artifacts = self.ingestor.ingest_file(path)
        sections = artifacts.sections
        chunks = artifacts.chunks
        tables = artifacts.tables
        log.info(
            "ingest parsed",
            sections=len(sections),
            chunks=len(chunks),
            tables=len(tables),
        )
        if not chunks:
            warnings.append("no chunks produced — document may be empty or unreadable")

        # ---- DB writes (single transaction) ----
        company = self._get_or_create_company(session, meta)
        document = Document(
            company_id=company.id,
            ticker=meta.ticker,
            company_name=meta.company_name,
            document_type=meta.document_type.value,
            fiscal_year=meta.fiscal_year,
            filing_date=meta.filing_date,
            source_url=meta.source_url,
            source_priority=meta.source_priority.value,
            page_count=artifacts.page_count or None,
            raw_path=str(path),
        )
        session.add(document)
        session.flush()  # populate document.id

        # Sections (kept in their own table for the /documents/{id} UI)
        for s in sections:
            session.add(
                DocumentSection(
                    document_id=document.id,
                    canonical_name=s.canonical_name,
                    raw_heading=s.raw_heading or None,
                    page_start=s.page_start,
                    page_end=s.page_end,
                    char_start=s.char_start,
                    char_end=s.char_end,
                    ordinal=s.ordinal,
                )
            )

        # Tables
        for t in tables:
            session.add(
                FinancialTable(
                    document_id=document.id,
                    section_canonical=t.section_canonical,
                    page=t.page,
                    caption=t.caption,
                    rows=t.rows,
                )
            )

        session.flush()

        # Chunks → PGVector. Deterministic source_ids let re-ingest
        # upsert the same chunks instead of duplicating.
        lc_docs: list[LCDocument] = []
        ids: list[str] = []
        seen: set[str] = set()
        duplicates = 0
        for chunk in chunks:
            sid = str(chunk_source_id(
                ticker=meta.ticker,
                document_type=meta.document_type.value,
                fiscal_year=meta.fiscal_year,
                filing_date=meta.filing_date,
                source_url=meta.source_url,
                raw_path=str(path),
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.chunk_text,
            ))
            if sid in seen:
                duplicates += 1
                continue
            seen.add(sid)

            enriched = self.enricher.enrich(chunk.chunk_text, chunk.section_canonical)
            lc_docs.append(
                LCDocument(
                    page_content=chunk.chunk_text,
                    metadata=_build_chunk_metadata(
                        sid=sid,
                        document_id=document.id,
                        chunk=chunk,
                        meta=meta,
                        enriched=enriched,
                    ),
                )
            )
            ids.append(sid)

        if lc_docs:
            self.vector_store.add_documents(lc_docs, ids=ids)

        if duplicates:
            warnings.append(f"deduped {duplicates} chunk(s) with identical content")
            log.info("chunks deduped", count=duplicates)

        return IngestionResult(
            document_id=document.id,
            ticker=meta.ticker,
            company_name=meta.company_name,
            document_type=meta.document_type,
            sections_count=len(sections),
            chunks_count=len(lc_docs),
            tables_count=len(tables),
            warnings=warnings,
        )

    @staticmethod
    def _get_or_create_company(session: "Session", meta: DocumentMetadata) -> Company:
        company = session.scalar(select(Company).where(Company.ticker == meta.ticker))
        if company is None:
            company = Company(ticker=meta.ticker, name=meta.company_name)
            session.add(company)
            session.flush()
        elif company.name != meta.company_name:
            company.name = meta.company_name
            session.flush()
        return company


def _build_chunk_metadata(
    *,
    sid: str,
    document_id: int,
    chunk,
    meta: DocumentMetadata,
    enriched,
) -> dict:
    """Flatten everything retrieval needs into a single JSON-safe dict.

    PGVector stores this as the ``cmetadata`` JSONB column, so it must
    contain only JSON-serializable values (strings, ints, lists, None).
    Dates are ISO strings.
    """
    return {
        "source_id": sid,
        "document_id": document_id,
        "chunk_index": chunk.chunk_index,
        "ticker": meta.ticker,
        "company_name": meta.company_name,
        "document_type": meta.document_type.value,
        "fiscal_year": meta.fiscal_year,
        "filing_date": meta.filing_date.isoformat() if meta.filing_date else None,
        "source_priority": meta.source_priority.value,
        "section": chunk.section_canonical,
        "subsection": chunk.raw_heading,
        "content_type": enriched.content_type,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "metric_tags": list(enriched.metric_tags or []),
        "risk_tags": list(enriched.risk_tags or []),
    }
