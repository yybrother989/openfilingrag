"""End-to-end ingestion pipeline.

Flow:
  1. Parse the file (PDF/HTML/text → ParsedDocument)
  2. Detect canonical sections
  3. Optionally extract financial tables (PDF only)
  4. Chunk each section
  5. Enrich chunks with content_type + metric/risk tags
  6. Embed chunks
  7. Upsert Company → Document → Sections → Tables → Chunks

Designed to be transactional: a single SQLAlchemy session does all writes
and commits at the end. On failure, nothing is partially persisted.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.errors import UnsupportedFormatError
from app.core.logging import get_logger
from app.db.models import (
    Company,
    Document,
    DocumentChunk,
    DocumentSection,
    FinancialTable,
)
from app.schemas.document import DocumentMetadata, IngestionResult

from .chunker import Chunker
from .html_parser import HTMLParser, TextParser
from .metadata_enricher import MetadataEnricher
from .pdf_parser import PDFParser
from .section_splitter import SectionSplitter
from .source_id import chunk_source_id
from .table_extractor import TableExtractor

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.services.embedding_service import EmbeddingService

log = get_logger(__name__)


class IngestionPipeline:
    """Orchestrates parsing → splitting → chunking → enrichment → embedding → DB write."""

    def __init__(
        self,
        embedding_service: "EmbeddingService",
        chunker: Chunker | None = None,
        splitter: SectionSplitter | None = None,
        enricher: MetadataEnricher | None = None,
    ) -> None:
        self.embedding_service = embedding_service
        self.chunker = chunker or Chunker()
        self.splitter = splitter or SectionSplitter()
        self.enricher = enricher or MetadataEnricher()
        self.pdf_parser = PDFParser()
        self.html_parser = HTMLParser()
        self.text_parser = TextParser()
        self.table_extractor = TableExtractor()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
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

        parsed = self._parse(path)
        sections = self.splitter.split(parsed.full_text, parsed.char_to_page)
        log.info("sections detected", count=len(sections))

        tables = []
        if path.suffix.lower() == ".pdf":
            tables = self.table_extractor.extract(path)
            log.info("tables detected", count=len(tables))

        chunks = self.chunker.chunk_sections(sections, parsed.char_to_page)
        log.info("chunks created", count=len(chunks))
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
            page_count=parsed.page_count,
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

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _parse(self, path: Path):
        ext = path.suffix.lower()
        if ext == ".pdf":
            return self.pdf_parser.parse(path)
        if ext in {".html", ".htm"}:
            return self.html_parser.parse(path)
        if ext in {".txt", ".md"}:
            return self.text_parser.parse(path)
        raise UnsupportedFormatError(f"unsupported file type: {ext or '<none>'}")

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
        """Map canonical_name → first ordinal where it appears.

        Used to attach chunks to their parent section row. If the same
        canonical section appears twice (rare but possible — e.g. an
        amended filing with two MD&A blocks) the chunks all link to the
        first occurrence; this is a known limitation.
        """
        out: dict[str, int] = {}
        for s in sections:
            out.setdefault(s.canonical_name, s.ordinal)
        return out
