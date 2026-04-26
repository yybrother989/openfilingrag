"""One-shot migration: ``document_chunks`` → ``langchain_pg_embedding``.

The Phase 2 retrieval rewrite reads chunks from PGVector's standard
schema. Existing chunks live in the legacy ``document_chunks`` table
(deleted from the ORM but still present in the database until after
this script runs).

What it does:
  * Reads rows in batches via raw SQL (the legacy ORM is gone).
  * Reuses each row's existing ``embedding`` so we don't pay to
    re-embed via OpenAI. Rows without an embedding are skipped (the
    target schema requires a vector); call out the skipped count so
    the operator can choose to re-embed manually.
  * Upserts into PGVector keyed by ``source_id``, so re-running is
    idempotent.

Usage::

    python scripts/migrate_chunks_to_pgvector.py [--batch 500] [--dry-run]

After verifying counts match, drop the legacy tables with the second
half of ``app/db/migrations/002_langchain_pgvector.sql``.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import sqlalchemy as sa
from langchain_core.documents import Document as LCDocument
from pgvector.sqlalchemy import Vector  # registers the vector type

from app.core.config import settings
from app.retrieval.pg_vector_store import build_pg_vector
from app.services.embedding_service import EmbeddingService


SELECT_BATCH = sa.text(
    """
    SELECT id, source_id::text AS source_id,
           document_id, chunk_index,
           ticker, company_name, document_type, fiscal_year,
           filing_date, source_priority,
           section, subsection, content_type,
           page_start, page_end,
           chunk_text,
           coalesce(metric_tags, '{}') AS metric_tags,
           coalesce(risk_tags,   '{}') AS risk_tags,
           embedding
      FROM document_chunks
     WHERE id > :after
     ORDER BY id ASC
     LIMIT :limit
    """
)


def _row_to_lcdoc(row: Any) -> tuple[LCDocument, list[float] | None, str]:
    sid = str(row.source_id)
    metadata = {
        "source_id": sid,
        "document_id": row.document_id,
        "chunk_index": row.chunk_index,
        "ticker": row.ticker,
        "company_name": row.company_name,
        "document_type": row.document_type,
        "fiscal_year": row.fiscal_year,
        "filing_date": row.filing_date.isoformat() if row.filing_date else None,
        "source_priority": row.source_priority,
        "section": row.section,
        "subsection": row.subsection,
        "content_type": row.content_type,
        "page_start": row.page_start,
        "page_end": row.page_end,
        "metric_tags": list(row.metric_tags or []),
        "risk_tags": list(row.risk_tags or []),
    }
    embedding = list(row.embedding) if row.embedding is not None else None
    return (
        LCDocument(page_content=row.chunk_text or "", metadata=metadata),
        embedding,
        sid,
    )


def main(batch: int = 500, dry_run: bool = False) -> int:
    engine = sa.create_engine(settings.database_url, pool_pre_ping=True)
    embedding_service = EmbeddingService()
    vs = build_pg_vector(embedding_service)

    # Make sure langchain_pg_collection / langchain_pg_embedding exist
    # before the operator runs 002_langchain_pgvector.sql Part A.
    vs.create_tables_if_not_exists()
    vs.create_collection()

    with engine.connect() as conn:
        total = conn.execute(sa.text("SELECT count(*) FROM document_chunks")).scalar() or 0

    print(f"document_chunks rows to migrate: {total} (batch={batch}, dry_run={dry_run})")
    if total == 0:
        return 0

    migrated = 0
    skipped_no_embedding = 0
    after_id = 0
    while True:
        with engine.connect() as conn:
            rows = conn.execute(SELECT_BATCH, {"after": after_id, "limit": batch}).fetchall()
        if not rows:
            break
        after_id = rows[-1].id

        ready_docs: list[LCDocument] = []
        ready_embeddings: list[list[float]] = []
        ready_ids: list[str] = []

        for row in rows:
            doc, emb, sid = _row_to_lcdoc(row)
            if emb is None:
                skipped_no_embedding += 1
                continue
            ready_docs.append(doc)
            ready_embeddings.append(emb)
            ready_ids.append(sid)

        if not dry_run and ready_docs:
            vs.add_embeddings(
                texts=[d.page_content for d in ready_docs],
                embeddings=ready_embeddings,
                metadatas=[d.metadata for d in ready_docs],
                ids=ready_ids,
            )

        migrated += len(ready_docs)
        print(
            f"  migrated {migrated}/{total} (after_id={after_id}, "
            f"skipped_no_embedding={skipped_no_embedding})"
        )

    print()
    print(f"done. migrated={migrated}, skipped_no_embedding={skipped_no_embedding}")
    if not dry_run:
        with engine.connect() as conn:
            new_count = conn.execute(
                sa.text("SELECT count(*) FROM langchain_pg_embedding")
            ).scalar() or 0
        print(f"langchain_pg_embedding row count after migration: {new_count}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--dry-run", action="store_true",
                    help="Read + count only; do not write to PGVector.")
    args = ap.parse_args()
    sys.exit(main(batch=args.batch, dry_run=args.dry_run))
