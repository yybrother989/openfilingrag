"""Pull SEC EDGAR filings for a ticker and ingest them.

Usage:

    python -m scripts.edgar_pull AAPL --types 10-K,10-Q --limit 2
    python -m scripts.edgar_pull MSFT --types 8-K --since 2025-01-01

No API key required. The first run downloads SEC's company-tickers map
into ``data/edgar_cache/`` (refreshed weekly).
"""

from __future__ import annotations

import argparse
from datetime import date

from app.core.logging import configure_logging, get_logger
from app.data_sources.sec_edgar import DEFAULT_FORM_TYPES
from app.db.session import session_scope
from app.services.edgar_ingest_service import EdgarIngestService
from app.services.report_service import get_workflow_deps

configure_logging()
log = get_logger(__name__)


def main() -> None:
    ap = argparse.ArgumentParser(description="Pull SEC EDGAR filings into OpenFilingRAG.")
    ap.add_argument("ticker", help="ticker symbol, e.g. AAPL")
    ap.add_argument(
        "--types",
        default=",".join(DEFAULT_FORM_TYPES),
        help=f"comma-separated form types (default: {','.join(DEFAULT_FORM_TYPES)})",
    )
    ap.add_argument("--limit", type=int, default=3, help="max filings to ingest (default 3)")
    ap.add_argument("--since", default=None, help="ISO date — only filings on/after this date")
    ap.add_argument("--company", default=None, help="override company display name")
    args = ap.parse_args()

    types = tuple(t.strip().upper() for t in args.types.split(",") if t.strip())
    since = date.fromisoformat(args.since) if args.since else None

    deps = get_workflow_deps()
    service = EdgarIngestService(embeddings=deps.embeddings)

    with session_scope() as session:
        summary = service.pull_and_ingest(
            ticker=args.ticker,
            session=session,
            types=types,
            limit=args.limit,
            since=since,
            company_name=args.company,
        )

    print()
    print(f"  ticker:           {summary.ticker}")
    print(f"  cik:              {summary.cik}")
    print(f"  filings listed:   {summary.listed}")
    print(f"  downloaded:       {summary.downloaded}")
    print(f"  ingested:         {summary.ingested}")
    print(f"  skipped (dupes):  {summary.skipped_existing}")
    print(f"  failures:         {summary.failures}")
    for r in summary.results:
        print(
            f"    + doc {r.document_id} {r.document_type.value} "
            f"sections={r.sections_count} chunks={r.chunks_count} tables={r.tables_count}"
        )


if __name__ == "__main__":
    main()
