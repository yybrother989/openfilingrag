"""Company endpoints — list + external enrichment via Alpha Vantage / Massive."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company
from app.db.session import get_db
from app.schemas.document import CompanyOut
from app.services.company_enrichment import CompanyEnrichmentService

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyOut])
def list_companies(session: Session = Depends(get_db)) -> list[CompanyOut]:
    rows = session.scalars(select(Company).order_by(Company.ticker.asc())).all()
    return [CompanyOut.model_validate(c) for c in rows]


@router.post("/{ticker}/enrich")
def enrich_company(ticker: str, session: Session = Depends(get_db)) -> dict:
    """Pull overview/news/financials from configured external providers
    and merge what's available into the ``companies`` row.
    """
    ticker = ticker.upper()
    service = CompanyEnrichmentService()
    if not service.configured_providers():
        raise HTTPException(
            status_code=400,
            detail=(
                "no external data sources configured — set ALPHA_VANTAGE_API_KEY "
                "and/or MASSIVE_API_KEY to enable enrichment"
            ),
        )
    bundle = service.fetch_all(ticker)
    company = service.enrich_company_row(session, ticker, bundle)
    session.commit()
    return {
        "ticker": ticker,
        "providers_used": service.configured_providers(),
        "company": CompanyOut.model_validate(company).model_dump(mode="json") if company else None,
        "bundle": bundle.model_dump(mode="json"),
    }
