"""Auto-discover any filing in ``data/sample_filings/`` and ingest it.

Drop a real 10-K PDF/HTML/TXT into ``data/sample_filings/``. If no real
filing is present, the script falls back to a tiny synthetic 10-K so the
demo path still works.

Metadata defaults can be overridden via env vars or CLI flags::

    INGEST_TICKER=AAPL INGEST_COMPANY="Apple Inc." python -m scripts.ingest_sample
"""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from app.core.logging import configure_logging, get_logger
from app.db.session import session_scope
from app.ingestion.pipeline import IngestionPipeline
from app.schemas.document import DocumentMetadata, DocumentType, SourcePriority
from app.services.report_service import get_workflow_deps

configure_logging()
log = get_logger(__name__)

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample_filings"
SUPPORTED_EXTS = {".pdf", ".html", ".htm", ".txt"}


def _discover() -> Path | None:
    if not SAMPLE_DIR.exists():
        return None
    for f in sorted(SAMPLE_DIR.iterdir()):
        if f.suffix.lower() in SUPPORTED_EXTS:
            return f
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest a sample filing into OpenFilingRAG.")
    ap.add_argument("--ticker", default=os.getenv("INGEST_TICKER", "ACME"))
    ap.add_argument("--company", default=os.getenv("INGEST_COMPANY", "Acme Corporation"))
    ap.add_argument(
        "--document-type",
        default=os.getenv("INGEST_DOCTYPE", "10-K"),
        choices=[d.value for d in DocumentType],
    )
    ap.add_argument("--fiscal-year", type=int, default=int(os.getenv("INGEST_FY", "2025")))
    ap.add_argument("--filing-date", default=os.getenv("INGEST_FILING_DATE", "2026-02-15"))
    ap.add_argument("--source-priority", default=SourcePriority.PRIMARY_FILING.value)
    ap.add_argument("--path", default=None, help="Override the auto-discovered path.")
    args = ap.parse_args()

    target = Path(args.path) if args.path else _discover()
    if target is None:
        log.warning(
            "no real filing found in data/sample_filings — generating synthetic fallback"
        )
        from scripts.create_sample_report import main as gen

        target = gen()

    log.info("ingest target", path=str(target))

    meta = DocumentMetadata(
        ticker=args.ticker.upper(),
        company_name=args.company,
        document_type=DocumentType(args.document_type),
        fiscal_year=args.fiscal_year,
        filing_date=date.fromisoformat(args.filing_date) if args.filing_date else None,
        source_priority=SourcePriority(args.source_priority),
    )

    deps = get_workflow_deps()
    pipeline = IngestionPipeline(embedding_service=deps.embedding)
    with session_scope() as session:
        result = pipeline.ingest(target, meta, session)
    log.info(
        "ingest complete",
        document_id=result.document_id,
        sections=result.sections_count,
        chunks=result.chunks_count,
        tables=result.tables_count,
    )
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
