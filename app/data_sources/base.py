"""Base abstractions for external financial-data providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class CompanyOverview(BaseModel):
    """Common subset of company-overview fields across data providers."""

    ticker: str
    name: str | None = None
    description: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    exchange: str | None = None
    market_cap: int | None = None
    raw: dict[str, Any] | None = None


class FilingNewsItem(BaseModel):
    title: str
    summary: str | None = None
    url: str | None = None
    published_at: str | None = None
    source: str | None = None
    sentiment: float | None = None
    raw: dict[str, Any] | None = None


class CompanyFinancials(BaseModel):
    """Lightweight, provider-agnostic snapshot of recent fundamentals."""

    ticker: str
    period: str | None = None
    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    eps_diluted: float | None = None
    operating_cash_flow: float | None = None
    free_cash_flow: float | None = None
    total_debt: float | None = None
    cash_and_equivalents: float | None = None
    raw: dict[str, Any] | None = None


class DataSource(ABC):
    """Common interface every external data provider implements."""

    name: str

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether the provider has an API key and is ready to make calls."""

    def overview(self, ticker: str) -> CompanyOverview | None:  # pragma: no cover
        """Return a company overview, or None if unsupported / not configured."""
        return None

    def latest_news(self, ticker: str, limit: int = 10) -> list[FilingNewsItem]:  # pragma: no cover
        return []

    def latest_financials(self, ticker: str) -> CompanyFinancials | None:  # pragma: no cover
        return None


class ProvidersBundle(BaseModel):
    """Aggregated payload returned by `services.company_enrichment.fetch_all`."""

    overview_alpha_vantage: CompanyOverview | None = None
    overview_massive: CompanyOverview | None = None
    news_alpha_vantage: list[FilingNewsItem] = Field(default_factory=list)
    news_massive: list[FilingNewsItem] = Field(default_factory=list)
    financials_alpha_vantage: CompanyFinancials | None = None
    financials_massive: CompanyFinancials | None = None
