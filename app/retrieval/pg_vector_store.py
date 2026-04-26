"""Factory for the project-wide ``PGVector`` instance.

Wraps ``langchain_postgres.PGVector`` with our settings and embedding
adapter. Used by :class:`HybridRetriever` for vector search and by the
ingestion pipeline to upsert chunk documents.
"""

from __future__ import annotations

from langchain_postgres import PGVector

from app.core.config import settings
from app.services.embedding_adapter import LangChainEmbeddings
from app.services.embedding_service import EmbeddingService

# Single collection name across the project. PGVector creates it on
# first use (with use_jsonb=True the metadata column is JSONB so we get
# rich filter syntax like {"$and": [...], "$in": [...]}).
COLLECTION_NAME = "filings_chunks"


def build_pg_vector(embedding_service: EmbeddingService) -> PGVector:
    return PGVector(
        embeddings=LangChainEmbeddings(embedding_service),
        collection_name=COLLECTION_NAME,
        connection=settings.database_url,
        embedding_length=embedding_service.dim,
        use_jsonb=True,
        create_extension=False,  # extension already created in 001 migration
    )
