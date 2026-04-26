"""Alpha Vantage REST client.

Docs: https://www.alphavantage.co/documentation/

We expose a small, opinionated subset useful for OpenFilingRAG:
* OVERVIEW — company overview / sector / description
* INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW — most recent annual report
* NEWS_SENTIMENT — recent news with sentiment

Rate limit: free tier is 5 req/min, 500 req/day. We keep call counts low
and the client is best-effort — failures degrade silently to ``None``/``[]``.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

from .base import (
    CompanyFinancials,
    CompanyOverview,
    DataSource,
    FilingNewsItem,
)

log = get_logger(__name__)

_BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageClient(DataSource):
    name = "alpha_vantage"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key or settings.alpha_vantage_api_key
        self._client = client or httpx.Client(timeout=timeout)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    # ------------------------------------------------------------------
    # Public methods (DataSource interface)
    # ------------------------------------------------------------------
    def overview(self, ticker: str) -> CompanyOverview | None:
        data = self._call({"function": "OVERVIEW", "symbol": ticker})
        if not data or not data.get("Symbol"):
            return None
        return CompanyOverview(
            ticker=data.get("Symbol", ticker),
            name=data.get("Name"),
            description=data.get("Description"),
            sector=data.get("Sector"),
            industry=data.get("Industry"),
            country=data.get("Country"),
            exchange=data.get("Exchange"),
            market_cap=_safe_int(data.get("MarketCapitalization")),
            raw=data,
        )

    def latest_news(self, ticker: str, limit: int = 10) -> list[FilingNewsItem]:
        data = self._call(
            {
                "function": "NEWS_SENTIMENT",
                "tickers": ticker,
                "limit": str(limit),
            }
        )
        if not data:
            return []
        feed = data.get("feed") or []
        out: list[FilingNewsItem] = []
        for item in feed[:limit]:
            sentiment = None
            for ts in item.get("ticker_sentiment", []) or []:
                if ts.get("ticker", "").upper() == ticker.upper():
                    try:
                        sentiment = float(ts.get("ticker_sentiment_score"))
                    except (ValueError, TypeError):
                        pass
                    break
            out.append(
                FilingNewsItem(
                    title=item.get("title", ""),
                    summary=item.get("summary"),
                    url=item.get("url"),
                    published_at=item.get("time_published"),
                    source=item.get("source"),
                    sentiment=sentiment,
                    raw=item,
                )
            )
        return out

    def latest_financials(self, ticker: str) -> CompanyFinancials | None:
        income = self._call({"function": "INCOME_STATEMENT", "symbol": ticker}) or {}
        cash = self._call({"function": "CASH_FLOW", "symbol": ticker}) or {}
        balance = self._call({"function": "BALANCE_SHEET", "symbol": ticker}) or {}

        annual_income = (income.get("annualReports") or [{}])[0]
        annual_cash = (cash.get("annualReports") or [{}])[0]
        annual_balance = (balance.get("annualReports") or [{}])[0]

        if not (annual_income or annual_cash or annual_balance):
            return None

        ocf = _safe_float(annual_cash.get("operatingCashflow"))
        capex = _safe_float(annual_cash.get("capitalExpenditures"))
        fcf = (ocf - capex) if (ocf is not None and capex is not None) else None

        return CompanyFinancials(
            ticker=ticker,
            period=annual_income.get("fiscalDateEnding"),
            revenue=_safe_float(annual_income.get("totalRevenue")),
            gross_profit=_safe_float(annual_income.get("grossProfit")),
            operating_income=_safe_float(annual_income.get("operatingIncome")),
            net_income=_safe_float(annual_income.get("netIncome")),
            eps_diluted=None,  # Alpha Vantage doesn't return EPS in the income endpoint
            operating_cash_flow=ocf,
            free_cash_flow=fcf,
            total_debt=_safe_float(annual_balance.get("longTermDebt")),
            cash_and_equivalents=_safe_float(
                annual_balance.get("cashAndCashEquivalentsAtCarryingValue")
            ),
            raw={
                "income": annual_income,
                "cash": annual_cash,
                "balance": annual_balance,
            },
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _call(self, params: dict[str, str]) -> dict[str, Any] | None:
        if not self.is_configured():
            log.debug("alpha vantage not configured, skipping", function=params.get("function"))
            return None
        params = {**params, "apikey": self.api_key}
        try:
            r = self._client.get(_BASE_URL, params=params)
            r.raise_for_status()
        except httpx.HTTPError as e:
            safe_err = str(e).replace(self.api_key or "<key>", "***")
            log.warning("alpha vantage call failed", err=safe_err, function=params.get("function"))
            return None
        try:
            data = r.json()
        except ValueError:
            return None
        # Alpha Vantage returns 200 with a "Note" key when rate-limited
        if isinstance(data, dict) and ("Note" in data or "Information" in data):
            log.warning("alpha vantage rate-limited", note=data.get("Note") or data.get("Information"))
            return None
        return data


def _safe_float(v: Any) -> float | None:
    try:
        if v in (None, "None", "-", ""):
            return None
        return float(v)
    except (ValueError, TypeError):
        return None


def _safe_int(v: Any) -> int | None:
    f = _safe_float(v)
    return int(f) if f is not None else None
