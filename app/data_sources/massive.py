"""Massive (https://massive.com) REST client.

Massive offers stock-market data with REST/WebSocket/flat-files for stocks,
options, futures, indices, forex, crypto, and economy/alternative data.

We expose the slice useful for OpenFilingRAG company enrichment:
* ticker overview / company details
* recent news for a ticker
* lightweight fundamentals (income / balance / cash flow latest period)

Endpoint paths follow the conventions documented at
https://massive.com/docs and the public reference URLs found via search:
``/v3/reference/tickers/{ticker}``, ``/v2/reference/news``, etc.
Configurable via ``MASSIVE_BASE_URL`` for alternate deployments.

Authentication: ``apiKey`` query parameter (Massive supports both header
and query forms; query is simpler and avoids preflight issues).
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


class MassiveClient(DataSource):
    name = "massive"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key or settings.massive_api_key
        self.base_url = (base_url or settings.massive_base_url).rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    # ------------------------------------------------------------------
    # Public methods (DataSource interface)
    # ------------------------------------------------------------------
    def overview(self, ticker: str) -> CompanyOverview | None:
        data = self._get(f"/v3/reference/tickers/{ticker.upper()}")
        if not data:
            return None
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, dict):
            return None
        return CompanyOverview(
            ticker=results.get("ticker", ticker),
            name=results.get("name"),
            description=results.get("description") or results.get("about"),
            sector=results.get("sic_description") or results.get("sector"),
            industry=results.get("industry"),
            country=results.get("locale") or results.get("country"),
            exchange=results.get("primary_exchange"),
            market_cap=_safe_int(results.get("market_cap")),
            raw=results,
        )

    def latest_news(self, ticker: str, limit: int = 10) -> list[FilingNewsItem]:
        data = self._get(
            "/v2/reference/news",
            params={"ticker": ticker.upper(), "limit": limit, "order": "desc"},
        )
        if not data:
            return []
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            return []
        out: list[FilingNewsItem] = []
        for item in results[:limit]:
            insights = item.get("insights") or []
            sentiment_score = None
            for ins in insights:
                if ins.get("ticker", "").upper() == ticker.upper():
                    s = ins.get("sentiment")
                    if isinstance(s, (int, float)):
                        sentiment_score = float(s)
                    elif isinstance(s, str):
                        sentiment_score = {"positive": 0.5, "negative": -0.5, "neutral": 0.0}.get(s.lower())
                    break
            out.append(
                FilingNewsItem(
                    title=item.get("title", ""),
                    summary=item.get("description"),
                    url=item.get("article_url") or item.get("url"),
                    published_at=item.get("published_utc"),
                    source=item.get("publisher", {}).get("name") if isinstance(item.get("publisher"), dict) else item.get("publisher"),
                    sentiment=sentiment_score,
                    raw=item,
                )
            )
        return out

    def latest_financials(self, ticker: str) -> CompanyFinancials | None:
        data = self._get(
            "/vX/reference/financials",
            params={"ticker": ticker.upper(), "limit": 1, "timeframe": "annual"},
        )
        if not data:
            return None
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list) or not results:
            return None
        latest = results[0]
        f = latest.get("financials") or {}
        income = f.get("income_statement") or {}
        bs = f.get("balance_sheet") or {}
        cf = f.get("cash_flow_statement") or {}

        def val(group: dict[str, Any], key: str) -> float | None:
            entry = group.get(key)
            if isinstance(entry, dict):
                return _safe_float(entry.get("value"))
            return _safe_float(entry)

        ocf = val(cf, "net_cash_flow_from_operating_activities")
        capex = val(cf, "net_cash_flow_from_investing_activities")  # rough proxy
        fcf = (ocf - abs(capex)) if (ocf is not None and capex is not None) else None

        return CompanyFinancials(
            ticker=ticker.upper(),
            period=latest.get("fiscal_period") or latest.get("end_date"),
            revenue=val(income, "revenues"),
            gross_profit=val(income, "gross_profit"),
            operating_income=val(income, "operating_income_loss"),
            net_income=val(income, "net_income_loss"),
            eps_diluted=val(income, "diluted_earnings_per_share"),
            operating_cash_flow=ocf,
            free_cash_flow=fcf,
            total_debt=val(bs, "long_term_debt"),
            cash_and_equivalents=val(bs, "cash"),
            raw=latest,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not self.is_configured():
            log.debug("massive not configured, skipping", path=path)
            return None
        url = f"{self.base_url}{path}"
        merged = {**(params or {}), "apiKey": self.api_key}
        try:
            r = self._client.get(url, params=merged)
            r.raise_for_status()
        except httpx.HTTPError as e:
            # Redact: httpx exception messages include the full URL with apiKey.
            safe_err = str(e).replace(self.api_key or "<key>", "***")
            log.warning("massive call failed", err=safe_err, path=path)
            return None
        try:
            return r.json()
        except ValueError:
            return None


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
