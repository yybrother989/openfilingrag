"""SEC EDGAR client — the free, official, default data source.

EDGAR is free and unauthenticated. SEC's policy requires a ``User-Agent``
that identifies the requester (see
https://www.sec.gov/os/accessing-edgar-data). We allow override via
``SEC_EDGAR_USER_AGENT`` env var and warn at startup if the default
placeholder is still in use.

This client exposes:

* :meth:`resolve_cik`   — ticker → CIK via the cached company tickers map
* :meth:`list_filings`  — recent filings for a company, filterable by form
* :meth:`download_filing` — fetches the primary document of a filing

It deliberately does **not** implement the ``DataSource.overview/news/
financials`` shape — those belong to the optional enrichment providers
(Alpha Vantage, Massive). EDGAR's role is the corpus itself.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import get_logger

from .base import DataSource

log = get_logger(__name__)

# Public, per SEC policy. No authentication.
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL_TEMPLATE = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL_TEMPLATE = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_doc}"
)
TICKER_CACHE_PATH = Path("data/edgar_cache/company_tickers.json")
TICKER_CACHE_TTL = timedelta(days=7)
DEFAULT_FORM_TYPES: tuple[str, ...] = ("10-K", "10-Q", "8-K")
PLACEHOLDER_USER_AGENT_FRAGMENT = "example.invalid"
# SEC asks for ≤ 10 req/s. Give ourselves a 150ms floor between calls.
MIN_REQUEST_INTERVAL_S = 0.15


class FilingRef(BaseModel):
    """One filing pulled from the SEC submissions endpoint."""

    cik: int
    ticker: str
    form: str
    accession_number: str  # e.g. "0000320193-24-000123"
    filing_date: date
    report_date: date | None = None
    primary_document: str
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    file_size: int | None = None

    @property
    def accession_no_dashes(self) -> str:
        return self.accession_number.replace("-", "")

    @property
    def archive_url(self) -> str:
        return ARCHIVE_URL_TEMPLATE.format(
            cik=self.cik,
            accession_no_dashes=self.accession_no_dashes,
            primary_doc=self.primary_document,
        )


class SECEdgarClient(DataSource):
    """Pull filings from SEC EDGAR. Free, no API key, identifies itself
    via the SEC-required ``User-Agent`` header.
    """

    name = "sec_edgar"

    def __init__(
        self,
        user_agent: str | None = None,
        cache_path: Path | None = None,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.user_agent = user_agent or settings.sec_edgar_user_agent
        self.cache_path = cache_path or TICKER_CACHE_PATH
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
        )
        self._last_request_at: float = 0.0
        self._ticker_map: dict[str, int] | None = None

        if PLACEHOLDER_USER_AGENT_FRAGMENT in self.user_agent:
            log.warning(
                "SEC_EDGAR_USER_AGENT is set to the default placeholder — "
                "set it in .env to identify yourself to SEC (e.g. "
                "'YourName your@email.com'). Requests may be throttled otherwise.",
                user_agent=self.user_agent,
            )

    # ------------------------------------------------------------------
    # DataSource shape (only is_configured is meaningful for EDGAR)
    # ------------------------------------------------------------------
    def is_configured(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # CIK resolution
    # ------------------------------------------------------------------
    def resolve_cik(self, ticker: str) -> int | None:
        """Return the CIK for a ticker, using a 7-day cached map."""
        ticker = ticker.upper().strip()
        if not ticker:
            return None
        return self._load_ticker_map().get(ticker)

    def _load_ticker_map(self) -> dict[str, int]:
        if self._ticker_map is not None:
            return self._ticker_map

        if self._cache_is_fresh():
            try:
                raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
                self._ticker_map = self._parse_ticker_map(raw)
                return self._ticker_map
            except (OSError, ValueError) as e:
                log.warning("ticker cache unreadable, refetching", err=str(e))

        log.info("fetching SEC ticker map", url=TICKER_MAP_URL)
        data = self._get_json(TICKER_MAP_URL)
        if not data:
            self._ticker_map = {}
            return self._ticker_map

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(data), encoding="utf-8")
        self._ticker_map = self._parse_ticker_map(data)
        return self._ticker_map

    def _cache_is_fresh(self) -> bool:
        if not self.cache_path.exists():
            return False
        age = datetime.fromtimestamp(self.cache_path.stat().st_mtime)
        return datetime.now() - age < TICKER_CACHE_TTL

    @staticmethod
    def _parse_ticker_map(raw: Any) -> dict[str, int]:
        """The SEC map is keyed by integer index, not ticker. Flatten it."""
        if not isinstance(raw, dict):
            return {}
        out: dict[str, int] = {}
        for entry in raw.values():
            if isinstance(entry, dict):
                t = str(entry.get("ticker", "")).upper().strip()
                cik = entry.get("cik_str") or entry.get("cik")
                try:
                    if t and cik is not None:
                        out[t] = int(cik)
                except (ValueError, TypeError):
                    continue
        return out

    # ------------------------------------------------------------------
    # Listing filings
    # ------------------------------------------------------------------
    def list_filings(
        self,
        ticker_or_cik: str | int,
        types: tuple[str, ...] = DEFAULT_FORM_TYPES,
        limit: int = 10,
        since: date | None = None,
    ) -> list[FilingRef]:
        """Return up to ``limit`` recent filings for the company.

        Filters by ``types`` (case-insensitive). If ``since`` is given,
        only filings on/after that date are returned.
        """
        cik, ticker = self._resolve_cik_and_ticker(ticker_or_cik)
        if cik is None:
            log.warning("could not resolve CIK", ticker_or_cik=ticker_or_cik)
            return []

        url = SUBMISSIONS_URL_TEMPLATE.format(cik=cik)
        data = self._get_json(url)
        if not data:
            return []

        return self._parse_submissions(
            data, cik=cik, ticker=ticker, types=types, limit=limit, since=since
        )

    def _resolve_cik_and_ticker(
        self, ticker_or_cik: str | int
    ) -> tuple[int | None, str]:
        if isinstance(ticker_or_cik, int):
            # Reverse lookup ticker (best-effort)
            tmap = self._load_ticker_map()
            ticker = next(
                (t for t, c in tmap.items() if c == ticker_or_cik),
                str(ticker_or_cik),
            )
            return ticker_or_cik, ticker
        s = str(ticker_or_cik).strip()
        if s.isdigit():
            cik = int(s)
            tmap = self._load_ticker_map()
            ticker = next((t for t, c in tmap.items() if c == cik), s)
            return cik, ticker
        ticker = s.upper()
        return self.resolve_cik(ticker), ticker

    @staticmethod
    def _parse_submissions(
        data: dict[str, Any],
        *,
        cik: int,
        ticker: str,
        types: tuple[str, ...],
        limit: int,
        since: date | None,
    ) -> list[FilingRef]:
        recent = (data.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        accession_numbers = recent.get("accessionNumber") or []
        filing_dates = recent.get("filingDate") or []
        report_dates = recent.get("reportDate") or []
        primary_docs = recent.get("primaryDocument") or []
        sizes = recent.get("size") or []

        wanted = {t.upper() for t in types}
        out: list[FilingRef] = []
        for i in range(min(len(forms), len(accession_numbers))):
            form = (forms[i] or "").upper()
            if form not in wanted:
                continue
            try:
                fdate = date.fromisoformat(filing_dates[i])
            except (ValueError, TypeError, IndexError):
                continue
            if since and fdate < since:
                continue
            try:
                rdate = date.fromisoformat(report_dates[i]) if report_dates[i] else None
            except (ValueError, TypeError, IndexError):
                rdate = None
            primary = primary_docs[i] if i < len(primary_docs) else ""
            if not primary:
                continue
            size = sizes[i] if i < len(sizes) and sizes[i] else None

            fy = (rdate or fdate).year
            fp = SECEdgarClient._derive_fiscal_period(form, rdate)

            out.append(
                FilingRef(
                    cik=cik,
                    ticker=ticker,
                    form=form,
                    accession_number=accession_numbers[i],
                    filing_date=fdate,
                    report_date=rdate,
                    primary_document=primary,
                    fiscal_year=fy,
                    fiscal_period=fp,
                    file_size=int(size) if isinstance(size, (int, str)) and str(size).isdigit() else None,
                )
            )
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _derive_fiscal_period(form: str, report_date: date | None) -> str | None:
        if form == "10-K":
            return "FY"
        if form == "10-Q" and report_date is not None:
            quarter = (report_date.month - 1) // 3 + 1
            return f"Q{quarter}"
        return None

    # ------------------------------------------------------------------
    # Downloading
    # ------------------------------------------------------------------
    def download_filing(self, ref: FilingRef, dest_root: Path) -> Path:
        """Download the primary document of a filing into a ticker/accession folder."""
        dest_dir = dest_root / ref.ticker / ref.accession_no_dashes
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / ref.primary_document
        if target.exists() and target.stat().st_size > 0:
            log.info("filing already cached locally", path=str(target))
            return target

        url = ref.archive_url
        log.info("downloading filing", ticker=ref.ticker, form=ref.form, accession=ref.accession_number)
        self._respect_rate_limit()
        try:
            r = self._client.get(url)
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("filing download failed", err=str(e), url=url)
            raise
        target.write_bytes(r.content)
        return target

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _get_json(self, url: str) -> dict[str, Any] | None:
        self._respect_rate_limit()
        try:
            r = self._client.get(url)
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("EDGAR call failed", err=str(e), url=_redact_url(url))
            return None
        try:
            return r.json()
        except ValueError:
            return None

    def _respect_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_S:
            time.sleep(MIN_REQUEST_INTERVAL_S - elapsed)
        self._last_request_at = time.monotonic()


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
_URL_QUERY_RE = re.compile(r"(\?|&)(api[-_]?key|apikey)=[^&]+", re.I)


def _redact_url(url: str) -> str:
    """SEC URLs don't carry keys, but be defensive in case a path picks one up."""
    return _URL_QUERY_RE.sub(r"\1\2=***", url)
