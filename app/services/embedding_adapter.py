"""LangChain ``Embeddings`` adapter over our :class:`EmbeddingService`.

Lets ``langchain_postgres.PGVector`` and any LangChain retriever speak to
our existing provider stack (HashEmbedder offline, OpenAIEmbedder online)
without instantiating a parallel client.
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings

from app.services.embedding_service import EmbeddingService


class LangChainEmbeddings(Embeddings):
    def __init__(self, service: EmbeddingService) -> None:
        self._service = service

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._service.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._service.embed_query(text)
