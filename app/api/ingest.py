"""Document ingest endpoint — accepts file upload OR a local server path."""

from __future__ import annotations

import shutil
import tempfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.ingestion.pipeline import IngestionPipeline
from app.schemas.document import (
    DocumentMetadata,
    DocumentType,
    IngestionResult,
    SourcePriority,
)
from app.services.report_service import get_workflow_deps

router = APIRouter(prefix="/documents", tags=["ingest"])


@router.post("/ingest", response_model=IngestionResult)
async def ingest_document(
    ticker: str = Form(...),
    company_name: str = Form(...),
    document_type: str = Form(...),
    fiscal_year: int | None = Form(None),
    filing_date: str | None = Form(None),
    source_url: str | None = Form(None),
    source_priority: str = Form(SourcePriority.PRIMARY_FILING.value),
    file: UploadFile | None = File(None),
    local_path: str | None = Form(None),
    session: Session = Depends(get_db),
) -> IngestionResult:
    if not file and not local_path:
        raise HTTPException(status_code=400, detail="provide either `file` or `local_path`")

    try:
        doc_type = DocumentType(document_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid document_type: {e}") from e
    try:
        priority = SourcePriority(source_priority)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid source_priority: {e}") from e

    parsed_date: date | None = None
    if filing_date:
        try:
            parsed_date = date.fromisoformat(filing_date)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="filing_date must be ISO YYYY-MM-DD") from e

    meta = DocumentMetadata(
        ticker=ticker.upper(),
        company_name=company_name,
        document_type=doc_type,
        fiscal_year=fiscal_year,
        filing_date=parsed_date,
        source_url=source_url,
        source_priority=priority,
    )

    # Resolve where the file lives
    cleanup_path: Path | None = None
    if file is not None:
        suffix = Path(file.filename or "").suffix or ".bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            input_path = Path(tmp.name)
            cleanup_path = input_path
    else:
        assert local_path
        input_path = Path(local_path)
        if not input_path.exists():
            raise HTTPException(status_code=400, detail=f"local_path does not exist: {local_path}")

    deps = get_workflow_deps()
    pipeline = IngestionPipeline(embedding_service=deps.embedding)
    try:
        result = pipeline.ingest(input_path, meta, session)
        session.commit()
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"ingest failed: {e}") from e
    finally:
        if cleanup_path is not None:
            cleanup_path.unlink(missing_ok=True)

    return result
