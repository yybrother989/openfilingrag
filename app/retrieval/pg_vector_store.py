"""Factory for the project-wide ``PGVector`` instance.

Wraps ``langchain_postgres.PGVector`` with our settings and embedding
adapter. Used by :class:`HybridRetriever` for vector search and by the
ingestion pipeline to upsert chunk documents.
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langchain_postgres import PGVector

from app.core.config import settings

# Single collection name across the project. PGVector creates it on
# first use (with use_jsonb=True the metadata column is JSONB so we get
# rich filter syntax like {"$and": [...], "$in": [...]}).
COLLECTION_NAME = "filings_chunks"


def build_pg_vector(embeddings: Embeddings) -> PGVector:
    # ``embedding_length`` is required when the table is created from
    # scratch. Read it from a probe vector when available; otherwise
    # fall back to the project default.
    try:
        probe = embeddings.embed_query("dimension probe")
        embedding_length = len(probe)
    except Exception:
        embedding_length = settings.pgvector_dim

    return PGVector(
        embeddings=embeddings,
        collection_name=COLLECTION_NAME,
        connection=settings.database_url,
        embedding_length=embedding_length,
        use_jsonb=True,
        create_extension=False,  # extension already created in 001 migration
    )
