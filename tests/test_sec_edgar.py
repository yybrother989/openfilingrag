"""SECEdgarClient unit tests.

All HTTP calls are intercepted via httpx.MockTransport — no real network.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.data_sources.sec_edgar import (
    ARCHIVE_URL_TEMPLATE,
    SUBMISSIONS_URL_TEMPLATE,
    TICKER_MAP_URL,
    FilingRef,
    SECEdgarClient,
)
from app.services.edgar_ingest_service import (
    FORM_TO_DOC_TYPE,
    EdgarIngestService,
)
from app.schemas.document import DocumentType


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
SAMPLE_TICKER_MAP = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
}


SAMPLE_SUBMISSIONS = {
    "cik": "320193",
    "filings": {
        "recent": {
            "form": ["10-K", "10-Q", "8-K", "S-3", "4"],
            "accessionNumber": [
                "0000320193-24-000123",
                "0000320193-24-000099",
                "0000320193-24-000088",
                "0000320193-24-000044",
                "0000320193-24-000033",
            ],
            "filingDate": [
                "2024-11-01",
                "2024-08-02",
                "2024-07-15",
                "2024-04-01",
                "2024-03-01",
            ],
            "reportDate": [
                "2024-09-28",
                "2024-06-29",
                "2024-07-15",
                "",
                "",
            ],
            "primaryDocument": [
                "aapl-20240928.htm",
                "aapl-20240629.htm",
                "aapl-8k-20240715.htm",
                "form-s3.htm",
                "wf-form4.xml",
            ],
            "size": [12345, 23456, 3456, 5000, 1234],
        }
    },
}


def _build_transport() -> httpx.MockTransport:
    """Routes all SEC URLs to canned responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == TICKER_MAP_URL:
            return httpx.Response(200, json=SAMPLE_TICKER_MAP)
        if url == SUBMISSIONS_URL_TEMPLATE.format(cik=320193):
            return httpx.Response(200, json=SAMPLE_SUBMISSIONS)
        if "aapl-20240928.htm" in url:
            return httpx.Response(
                200,
                content=b"<html><body>Item 1. Business. Apple makes things.</body></html>",
            )
        return httpx.Response(404, text="not mocked: " + url)

    return httpx.MockTransport(handler)


@pytest.fixture
def edgar_client(tmp_path: Path) -> SECEdgarClient:
    transport = _build_transport()
    httpx_client = httpx.Client(transport=transport, headers={"User-Agent": "test/1.0 t@t"})
    return SECEdgarClient(
        user_agent="test/1.0 t@t",
        cache_path=tmp_path / "company_tickers.json",
        client=httpx_client,
    )


# ----------------------------------------------------------------------
# CIK resolution
# ----------------------------------------------------------------------
def test_resolve_cik_returns_correct_int(edgar_client: SECEdgarClient) -> None:
    assert edgar_client.resolve_cik("AAPL") == 320193
    assert edgar_client.resolve_cik("aapl") == 320193  # case-insensitive
    assert edgar_client.resolve_cik("MSFT") == 789019
    assert edgar_client.resolve_cik("DOES_NOT_EXIST") is None


def test_ticker_map_is_cached(edgar_client: SECEdgarClient, tmp_path: Path) -> None:
    edgar_client.resolve_cik("AAPL")
    cache_file = edgar_client.cache_path
    assert cache_file.exists()
    raw = json.loads(cache_file.read_text())
    assert raw == SAMPLE_TICKER_MAP


# ----------------------------------------------------------------------
# Filing list
# ----------------------------------------------------------------------
def test_list_filings_filters_by_form_type(edgar_client: SECEdgarClient) -> None:
    refs = edgar_client.list_filings("AAPL", types=("10-K", "10-Q", "8-K"), limit=10)
    forms = [r.form for r in refs]
    assert forms == ["10-K", "10-Q", "8-K"]
    # S-3 and Form 4 must be filtered out
    assert "S-3" not in forms
    assert "4" not in forms


def test_list_filings_respects_limit(edgar_client: SECEdgarClient) -> None:
    refs = edgar_client.list_filings("AAPL", limit=2)
    assert len(refs) == 2


def test_list_filings_respects_since(edgar_client: SECEdgarClient) -> None:
    refs = edgar_client.list_filings("AAPL", since=date(2024, 8, 1))
    for r in refs:
        assert r.filing_date >= date(2024, 8, 1)
    assert any(r.form == "10-K" for r in refs)


def test_list_filings_populates_metadata(edgar_client: SECEdgarClient) -> None:
    refs = edgar_client.list_filings("AAPL", types=("10-K",), limit=1)
    assert len(refs) == 1
    r = refs[0]
    assert r.ticker == "AAPL"
    assert r.cik == 320193
    assert r.form == "10-K"
    assert r.fiscal_year == 2024
    assert r.fiscal_period == "FY"
    assert r.primary_document == "aapl-20240928.htm"


def test_list_filings_10q_derives_quarter(edgar_client: SECEdgarClient) -> None:
    refs = edgar_client.list_filings("AAPL", types=("10-Q",), limit=1)
    assert refs[0].fiscal_period == "Q2"  # June filing → Q2


# ----------------------------------------------------------------------
# URL construction
# ----------------------------------------------------------------------
def test_archive_url_construction() -> None:
    ref = FilingRef(
        cik=320193,
        ticker="AAPL",
        form="10-K",
        accession_number="0000320193-24-000123",
        filing_date=date(2024, 11, 1),
        primary_document="aapl-20240928.htm",
        fiscal_year=2024,
    )
    expected = ARCHIVE_URL_TEMPLATE.format(
        cik=320193,
        accession_no_dashes="000032019324000123",
        primary_doc="aapl-20240928.htm",
    )
    assert ref.archive_url == expected
    assert ref.accession_no_dashes == "000032019324000123"


# ----------------------------------------------------------------------
# Form → DocumentType mapping
# ----------------------------------------------------------------------
def test_form_to_document_type_mapping() -> None:
    assert FORM_TO_DOC_TYPE["10-K"] == DocumentType.TEN_K
    assert FORM_TO_DOC_TYPE["10-K/A"] == DocumentType.TEN_K
    assert FORM_TO_DOC_TYPE["10-Q"] == DocumentType.TEN_Q
    assert FORM_TO_DOC_TYPE["8-K"] == DocumentType.EIGHT_K


# ----------------------------------------------------------------------
# download_filing writes to the right path
# ----------------------------------------------------------------------
def test_download_filing_writes_under_ticker_accession_dir(
    edgar_client: SECEdgarClient, tmp_path: Path
) -> None:
    refs = edgar_client.list_filings("AAPL", types=("10-K",), limit=1)
    ref = refs[0]
    dest_root = tmp_path / "filings"
    path = edgar_client.download_filing(ref, dest_root)
    assert path.exists()
    assert path.parent.name == ref.accession_no_dashes
    assert path.parent.parent.name == "AAPL"
    assert b"Apple makes things" in path.read_bytes()


# ----------------------------------------------------------------------
# EdgarIngestService
# ----------------------------------------------------------------------
def test_metadata_built_from_filing_ref() -> None:
    ref = FilingRef(
        cik=320193,
        ticker="AAPL",
        form="10-K",
        accession_number="0000320193-24-000123",
        filing_date=date(2024, 11, 1),
        report_date=date(2024, 9, 28),
        primary_document="aapl-20240928.htm",
        fiscal_year=2024,
    )
    meta = EdgarIngestService._build_metadata(ref, company_name="Apple Inc.")
    assert meta.ticker == "AAPL"
    assert meta.company_name == "Apple Inc."
    assert meta.document_type == DocumentType.TEN_K
    assert meta.fiscal_year == 2024
    assert meta.filing_date == date(2024, 11, 1)
    assert meta.source_url.endswith("aapl-20240928.htm")
