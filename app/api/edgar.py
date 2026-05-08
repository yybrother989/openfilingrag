"""SEC EDGAR endpoints — list filings, fetch + ingest by ticker."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.data_sources.sec_edgar import DEFAULT_FORM_TYPES
from app.db.session import get_db
from app.services.edgar_ingest_service import EdgarIngestService
from app.services.report_service import get_workflow_deps

router = APIRouter(prefix="/sources/edgar", tags=["edgar"])


class EdgarPullRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=16)
    types: list[str] = Field(default_factory=lambda: list(DEFAULT_FORM_TYPES))
    limit: int = Field(default=3, ge=1, le=20)
    since: date | None = None
    company_name: str | None = None


@router.get("/filings/{ticker}")
def list_filings(
    ticker: str,
    types: str = Query(",".join(DEFAULT_FORM_TYPES)),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    """Preview which filings EDGAR has for this ticker, without ingesting."""
    deps = get_workflow_deps()
    service = EdgarIngestService(embeddings=deps.embeddings)
    type_tuple = tuple(t.strip().upper() for t in types.split(",") if t.strip())
    refs = service.list_filings(ticker, type_tuple, limit=limit)
    if not refs:
        # Provide a hint about CIK resolution failures
        cik = service.edgar.resolve_cik(ticker)
        if cik is None:
            raise HTTPException(
                status_code=404,
                detail=f"Could not resolve ticker '{ticker.upper()}' to a SEC CIK.",
            )
    return {
        "ticker": ticker.upper(),
        "cik": service.edgar.resolve_cik(ticker),
        "count": len(refs),
        "filings": [r.model_dump(mode="json") for r in refs],
    }


@router.post("/pull")
def pull_filings(
    body: EdgarPullRequest,
    session: Session = Depends(get_db),
) -> dict:
    """Fetch + ingest filings for a ticker. Idempotent (dedupes by source URL)."""
    deps = get_workflow_deps()
    service = EdgarIngestService(embeddings=deps.embeddings)
    summary = service.pull_and_ingest(
        ticker=body.ticker,
        session=session,
        types=body.types,
        limit=body.limit,
        since=body.since,
        company_name=body.company_name,
    )
    return {
        "ticker": summary.ticker,
        "cik": summary.cik,
        "listed": summary.listed,
        "downloaded": summary.downloaded,
        "ingested": summary.ingested,
        "skipped_existing": summary.skipped_existing,
        "failures": summary.failures,
        "results": [r.model_dump(mode="json") for r in summary.results],
    }
