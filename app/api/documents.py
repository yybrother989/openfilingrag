"""Document listing + detail + lifecycle endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.session import get_db
from app.ingestion.pipeline import IngestionPipeline
from app.schemas.document import DocumentOut, IngestionResult, LocalFileEntry
from app.services.document_service import (
    delete_document,
    get_document,
    list_documents,
    list_local_files,
    metadata_for_reindex,
)
from app.services.report_service import get_workflow_deps

router = APIRouter(prefix="/documents", tags=["documents"])
log = get_logger(__name__)


@router.get("", response_model=list[DocumentOut])
def list_docs(
    ticker: str | None = None,
    limit: int = 100,
    session: Session = Depends(get_db),
) -> list[DocumentOut]:
    return list_documents(session, ticker=ticker, limit=limit)


@router.get("/local-files", response_model=list[LocalFileEntry])
def list_local_document_files() -> list[LocalFileEntry]:
    return list_local_files()


@router.get("/{document_id}")
def get_doc(document_id: int, session: Session = Depends(get_db)) -> dict:
    result = get_document(session, document_id)
    if not result:
        raise HTTPException(status_code=404, detail="document not found")
    doc, sections = result
    return {
        "document": doc.model_dump(mode="json"),
        "sections": [s.model_dump(mode="json") for s in sections],
    }


@router.delete("/{document_id}", status_code=204)
def delete_doc(document_id: int, session: Session = Depends(get_db)) -> Response:
    """Delete the document and cascade its sections, chunks, tables, and
    evidence cache rows linked via chunk_id.
    """
    if not delete_document(session, document_id):
        raise HTTPException(status_code=404, detail="document not found")
    session.commit()
    return Response(status_code=204)


@router.post("/{document_id}/reindex", response_model=IngestionResult)
def reindex_doc(document_id: int, session: Session = Depends(get_db)) -> IngestionResult:
    """Re-ingest a document from its on-disk source.

    Drops the existing document (cascading chunks/sections/tables) and
    re-runs the pipeline. The deterministic source_id (#5) means any
    cached evidence rows that pointed at the old chunks will resolve
    again to the new ones with identical text.
    """
    captured = metadata_for_reindex(session, document_id)
    if not captured:
        raise HTTPException(
            status_code=400,
            detail="document not found, or its raw_path is missing on disk",
        )
    raw_path, meta = captured

    if not delete_document(session, document_id):
        raise HTTPException(status_code=404, detail="document not found")
    session.flush()  # let the pipeline see a clean slate within the same txn

    deps = get_workflow_deps()
    pipeline = IngestionPipeline(embedding_service=deps.embedding)
    try:
        result = pipeline.ingest(raw_path, meta, session)
        session.commit()
    except Exception as e:
        session.rollback()
        log.exception("reindex failed", document_id=document_id, err=str(e))
        raise HTTPException(status_code=500, detail=f"reindex failed: {e}") from e
    return result
