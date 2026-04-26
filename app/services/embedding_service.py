"""Embedding service with pluggable providers.

The :class:`EmbeddingService` exposes ``embed_documents`` and
``embed_query``. The provider is auto-selected based on env config:

* ``openai`` — calls the OpenAI embeddings API (default model
  ``text-embedding-3-small``, 1536-dim).
* ``hash`` — deterministic, dependency-free 1536-dim vectors derived
  from token hashes. Used in mock mode and tests so retrieval ordering
  is meaningful even without an API key.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol

from app.core.config import settings
from app.core.errors import EmbeddingError
from app.core.logging import get_logger

log = get_logger(__name__)

_DEFAULT_DIM = 1536
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")


class _Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


# ----------------------------------------------------------------------
# Hash embedder — deterministic, free, offline
# ----------------------------------------------------------------------
class HashEmbedder:
    """Deterministic bag-of-tokens vector with TF weighting.

    Each token bucketed into ``dim`` slots via SHA-256 mod dim. Resulting
    vector is L2-normalized so cosine similarity == dot product.
    Two semantically-similar prose snippets share many tokens and end up
    with similar vectors — sufficient signal for tests and demos.
    """

    def __init__(self, dim: int = _DEFAULT_DIM) -> None:
        self.dim = dim

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        tokens = [t.lower() for t in _TOKEN_RE.findall(text or "")]
        vec = [0.0] * self.dim
        if not tokens:
            return vec
        for tok in tokens:
            h = hashlib.sha256(tok.encode("utf-8")).digest()
            slot = int.from_bytes(h[:4], "big") % self.dim
            sign = 1.0 if (h[4] & 1) else -1.0
            vec[slot] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


# ----------------------------------------------------------------------
# OpenAI embedder
# ----------------------------------------------------------------------
class OpenAIEmbedder:
    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise EmbeddingError("openai package is required for OpenAIEmbedder") from e
        self._client = OpenAI(api_key=api_key or settings.openai_api_key)
        self.model = model or settings.embedding_model or "text-embedding-3-small"
        self.dim = _DEFAULT_DIM  # both -3-small and -3-large default to 1536/3072

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        # Batch in chunks of 96 to stay well below OpenAI's per-request limit
        for i in range(0, len(texts), 96):
            batch = texts[i : i + 96]
            try:
                resp = self._client.embeddings.create(input=list(batch), model=self.model)
            except Exception as e:
                raise EmbeddingError(f"OpenAI embeddings call failed: {e}") from e
            out.extend([d.embedding for d in resp.data])
        return out

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


# ----------------------------------------------------------------------
# Service facade
# ----------------------------------------------------------------------
class EmbeddingService:
    """Front door for all embedding calls. Selects provider via settings."""

    def __init__(self, embedder: _Embedder | None = None) -> None:
        if embedder is not None:
            self._embedder: _Embedder = embedder
        else:
            self._embedder = self._build_default()
        log.info(
            "embedding service ready",
            provider=type(self._embedder).__name__,
            dim=self._embedder.dim,
        )

    @staticmethod
    def _build_default() -> _Embedder:
        provider = settings.effective_embedding_provider
        if provider == "openai":
            return OpenAIEmbedder()
        return HashEmbedder(dim=settings.pgvector_dim)

    @property
    def dim(self) -> int:
        return self._embedder.dim

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embedder.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embedder.embed_query(text)
