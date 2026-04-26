"""pgvector cosine-similarity search over document_chunks."""

from __future__ import annotations

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from app.db.models import DocumentChunk


class VectorStore:
    """Thin wrapper around a pgvector cosine-distance query.

    pgvector returns *distance*, smaller=closer. We translate to a
    similarity score in [0, 1] via ``1 - cosine_distance / 2`` (cosine
    distance in pgvector ranges 0–2).
    """

    def search(
        self,
        session: Session,
        embedding: list[float],
        where: ColumnElement | None = None,
        k: int = 50,
    ) -> list[tuple[DocumentChunk, float]]:
        if not embedding:
            return []
        distance = DocumentChunk.embedding.cosine_distance(embedding)
        stmt = (
            select(DocumentChunk, distance.label("distance"))
            .order_by(distance.asc())
            .limit(k)
        )
        if where is not None:
            stmt = stmt.where(where)

        rows = session.execute(stmt).all()
        out: list[tuple[DocumentChunk, float]] = []
        for chunk, dist in rows:
            sim = max(0.0, min(1.0, 1.0 - (float(dist) / 2.0)))
            out.append((chunk, sim))
        return out
