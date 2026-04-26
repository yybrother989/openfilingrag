"""End-to-end ingestion pipeline.

Flow:
  1. Parse + chunk + extract tables in one Docling pass (or plain-text
     fallback for .txt). See :mod:`.docling_adapter`.
  2. Enrich chunks with content_type + metric/risk tags.
  3. Embed chunks.
  4. Upsert Company → Document → Sections → Tables → Chunks.

Designed to be transactional: a single SQLAlchemy session does all writes
and commits at the end. On failure, nothing is partially persisted.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models import (
    Company,
    Document,
    DocumentChunk,
    DocumentSection,
    FinancialTable,
)
from app.schemas.document import DocumentMetadata, IngestionResult

from .docling_adapter import DoclingIngestor
from .metadata_enricher import MetadataEnricher
from .source_id import chunk_source_id

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.services.embedding_service import EmbeddingService

log = get_logger(__name__)


class IngestionPipeline:
    """Orchestrates Docling parsing/chunking → enrichment → embedding → DB write."""

    def __init__(
        self,
        embedding_service: "EmbeddingService",
        ingestor: DoclingIngestor | None = None,
        enricher: MetadataEnricher | None = None,
    ) -> None:
        self.embedding_service = embedding_service
        self.ingestor = ingestor or DoclingIngestor()
        self.enricher = enricher or MetadataEnricher()

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

        # Embed all chunks in a batch
        chunk_texts = [c.chunk_text for c in chunks]
        embeddings = self.embedding_service.embed_documents(chunk_texts) if chunk_texts else []

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

        # Sections
        section_id_by_ordinal: dict[int, int] = {}
        for s in sections:
            row = DocumentSection(
                document_id=document.id,
                canonical_name=s.canonical_name,
                raw_heading=s.raw_heading or None,
                page_start=s.page_start,
                page_end=s.page_end,
                char_start=s.char_start,
                char_end=s.char_end,
                ordinal=s.ordinal,
            )
            session.add(row)
            session.flush()
            section_id_by_ordinal[s.ordinal] = row.id

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

        # Chunks — assign deterministic source_ids and dedup within the
        # batch so a parser that emits the same paragraph twice doesn't
        # create two rows that fight over the unique constraint.
        ordinal_lookup = self._build_section_ordinal_lookup(sections)
        seen_source_ids: set = set()
        duplicates = 0
        for chunk, embedding in zip(chunks, embeddings, strict=False):
            sid = chunk_source_id(
                ticker=meta.ticker,
                document_type=meta.document_type.value,
                fiscal_year=meta.fiscal_year,
                filing_date=meta.filing_date,
                source_url=meta.source_url,
                raw_path=str(path),
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.chunk_text,
            )
            if sid in seen_source_ids:
                duplicates += 1
                continue
            seen_source_ids.add(sid)

            enriched = self.enricher.enrich(chunk.chunk_text, chunk.section_canonical)
            ordinal = ordinal_lookup.get(chunk.section_canonical)
            session.add(
                DocumentChunk(
                    source_id=sid,
                    document_id=document.id,
                    section_id=section_id_by_ordinal.get(ordinal) if ordinal is not None else None,
                    ticker=meta.ticker,
                    company_name=meta.company_name,
                    document_type=meta.document_type.value,
                    fiscal_year=meta.fiscal_year,
                    filing_date=meta.filing_date,
                    source_priority=meta.source_priority.value,
                    section=chunk.section_canonical,
                    subsection=chunk.raw_heading,
                    content_type=enriched.content_type,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    chunk_index=chunk.chunk_index,
                    chunk_text=chunk.chunk_text,
                    metric_tags=enriched.metric_tags,
                    risk_tags=enriched.risk_tags,
                    embedding=embedding,
                )
            )

        if duplicates:
            warnings.append(f"deduped {duplicates} chunk(s) with identical content")
            log.info("chunks deduped", count=duplicates)

        session.flush()

        return IngestionResult(
            document_id=document.id,
            ticker=meta.ticker,
            company_name=meta.company_name,
            document_type=meta.document_type,
            sections_count=len(sections),
            chunks_count=len(chunks),
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

    @staticmethod
    def _build_section_ordinal_lookup(sections) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in sections:
            out.setdefault(s.canonical_name, s.ordinal)
        return out
