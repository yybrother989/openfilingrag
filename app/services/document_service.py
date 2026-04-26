"""Thin orchestration helpers for document-related API endpoints."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentSection
from app.schemas.document import (
    DocumentMetadata,
    DocumentOut,
    DocumentType,
    LocalFileEntry,
    SectionOut,
    SourcePriority,
)

LOCAL_FILINGS_ROOT = Path(__file__).resolve().parents[2] / "data" / "sample_filings"


def list_documents(session: Session, ticker: str | None = None, limit: int = 100) -> list[DocumentOut]:
    stmt = select(Document).order_by(desc(Document.created_at)).limit(limit)
    if ticker:
        stmt = stmt.where(Document.ticker == ticker.upper())
    rows: Sequence[Document] = session.scalars(stmt).all()
    return [_to_out(d) for d in rows]


def get_document(session: Session, document_id: int) -> tuple[DocumentOut, list[SectionOut]] | None:
    doc = session.get(Document, document_id)
    if not doc:
        return None
    sections = session.scalars(
        select(DocumentSection)
        .where(DocumentSection.document_id == document_id)
        .order_by(DocumentSection.ordinal.asc())
    ).all()
    return _to_out(doc), [SectionOut.model_validate(s) for s in sections]


def delete_document(session: Session, document_id: int) -> bool:
    """Delete a document. Cascade FKs drop sections, chunks, tables, and
    evidence_items linked via chunk_id. Returns False if the doc didn't
    exist (so the API can 404 cleanly).
    """
    doc = session.get(Document, document_id)
    if not doc:
        return False
    session.delete(doc)
    return True


def metadata_for_reindex(session: Session, document_id: int) -> tuple[Path, DocumentMetadata] | None:
    """Capture a document's identity + on-disk source so it can be re-ingested.

    Returns ``None`` if the document or its raw_path is missing on disk —
    we refuse to silently drop the existing document in that case.
    """
    doc = session.get(Document, document_id)
    if not doc or not doc.raw_path:
        return None
    raw_path = Path(doc.raw_path)
    if not raw_path.exists():
        return None
    try:
        doc_type = DocumentType(doc.document_type)
    except ValueError:
        doc_type = DocumentType.OTHER
    try:
        priority = SourcePriority(doc.source_priority)
    except ValueError:
        priority = SourcePriority.PRIMARY_FILING
    meta = DocumentMetadata(
        ticker=doc.ticker,
        company_name=doc.company_name,
        document_type=doc_type,
        fiscal_year=doc.fiscal_year,
        filing_date=doc.filing_date,
        source_url=doc.source_url,
        source_priority=priority,
    )
    return raw_path, meta


def list_local_files() -> list[LocalFileEntry]:
    if not LOCAL_FILINGS_ROOT.exists():
        return []

    entries: list[LocalFileEntry] = []
    for path in sorted(LOCAL_FILINGS_ROOT.rglob("*")):
        try:
            relative_path = path.relative_to(LOCAL_FILINGS_ROOT)
        except ValueError:
            continue
        if relative_path.name.startswith("."):
            continue
        stat = path.stat()
        is_dir = path.is_dir()
        entries.append(
            LocalFileEntry(
                name=path.name,
                relative_path=relative_path.as_posix(),
                local_path=str(path.resolve()),
                kind="directory" if is_dir else "file",
                extension=None if is_dir else path.suffix.lower() or None,
                size_bytes=None if is_dir else stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )
        )
    return entries


def _to_out(doc: Document) -> DocumentOut:
    return DocumentOut.model_validate(
        {
            "id": doc.id,
            "ticker": doc.ticker,
            "company_name": doc.company_name,
            "document_type": doc.document_type,
            "fiscal_year": doc.fiscal_year,
            "filing_date": doc.filing_date,
            "source_url": doc.source_url,
            "source_priority": doc.source_priority,
            "page_count": doc.page_count,
            "sections_count": len(doc.sections) if doc.sections is not None else None,
            "chunks_count": len(doc.chunks) if doc.chunks is not None else None,
            "tables_count": len(doc.tables) if doc.tables is not None else None,
            "raw_path": doc.raw_path,
            "created_at": doc.created_at,
        }
    )
