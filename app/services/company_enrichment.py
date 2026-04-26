"""Aggregates external data-source providers and merges into the DB.

Used by the ``POST /companies/{ticker}/enrich`` endpoint and at ingest
time to opportunistically backfill ``Company.sector`` / ``industry``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.data_sources import (
    AlphaVantageClient,
    DataSource,
    MassiveClient,
    ProvidersBundle,
)
from app.db.models import Company

log = get_logger(__name__)


class CompanyEnrichmentService:
    def __init__(self, providers: list[DataSource] | None = None) -> None:
        self.providers: list[DataSource] = providers or [
            AlphaVantageClient(),
            MassiveClient(),
        ]

    def configured_providers(self) -> list[str]:
        return [p.name for p in self.providers if p.is_configured()]

    def fetch_all(self, ticker: str) -> ProvidersBundle:
        bundle = ProvidersBundle()
        for p in self.providers:
            if not p.is_configured():
                continue
            try:
                ov = p.overview(ticker)
                if ov:
                    setattr(bundle, f"overview_{p.name}", ov)
            except Exception as e:  # provider-defensive
                log.warning("provider overview failed", provider=p.name, err=str(e))
            try:
                news = p.latest_news(ticker, limit=10)
                if news:
                    setattr(bundle, f"news_{p.name}", news)
            except Exception as e:
                log.warning("provider news failed", provider=p.name, err=str(e))
            try:
                fin = p.latest_financials(ticker)
                if fin:
                    setattr(bundle, f"financials_{p.name}", fin)
            except Exception as e:
                log.warning("provider financials failed", provider=p.name, err=str(e))
        return bundle

    def enrich_company_row(
        self,
        session: Session,
        ticker: str,
        bundle: ProvidersBundle | None = None,
    ) -> Company | None:
        """Persist sector/industry into ``companies`` if any provider returned them."""
        bundle = bundle or self.fetch_all(ticker)
        company = session.scalar(select(Company).where(Company.ticker == ticker))
        if not company:
            return None

        # Prefer alpha_vantage overview, fall back to massive
        ov = bundle.overview_alpha_vantage or bundle.overview_massive
        if ov:
            if ov.sector and not company.sector:
                company.sector = ov.sector
            if ov.industry and not company.industry:
                company.industry = ov.industry
            extra = company.extra or {}
            extra.setdefault("provider_overviews", {})
            if bundle.overview_alpha_vantage:
                extra["provider_overviews"]["alpha_vantage"] = (
                    bundle.overview_alpha_vantage.model_dump(mode="json")
                )
            if bundle.overview_massive:
                extra["provider_overviews"]["massive"] = (
                    bundle.overview_massive.model_dump(mode="json")
                )
            company.extra = extra
            session.flush()
        return company
