"""Postgres full-text search over the chunks.tsv generated column.

Uses ``plainto_tsquery`` so callers can pass natural-language queries.
Returns ``(chunk, ts_rank_cd)`` tuples sorted by relevance — only the
ordering is consumed downstream (RRF fusion in ``HybridRetriever``), so
the raw ``ts_rank_cd`` value is exposed unmodified for debugging /
observability rather than min-max scaled.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.db.models import DocumentChunk


class KeywordSearch:
    def search(
        self,
        session: Session,
        query: str,
        where: ColumnElement | None = None,
        k: int = 50,
    ) -> list[tuple[DocumentChunk, float]]:
        if not query.strip():
            return []
        ts = func.plainto_tsquery("english", query)
        rank = func.ts_rank_cd(DocumentChunk.tsv, ts)
        stmt = (
            select(DocumentChunk, rank.label("rank"))
            .where(DocumentChunk.tsv.op("@@")(ts))
            .order_by(rank.desc())
            .limit(k)
        )
        if where is not None:
            stmt = stmt.where(where)

        rows = session.execute(stmt).all()
        return [(chunk, float(r)) for chunk, r in rows]
