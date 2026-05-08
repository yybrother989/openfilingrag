"""Deterministic offline embedder, native LangChain ``Embeddings`` interface.

Same SHA-256 token-bucketing algorithm as the original
``HashEmbedder`` from the deleted ``embedding_service.py``, but inheriting
from :class:`langchain_core.embeddings.Embeddings` so it plugs into
PGVector / retrievers without a wrapper.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

from langchain_core.embeddings import Embeddings

_DEFAULT_DIM = 1536
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")


class HashEmbeddings(Embeddings):
    """Bag-of-tokens vector with TF weighting, L2-normalized.

    Each token bucketed into ``dim`` slots via SHA-256 mod dim. Two
    semantically-similar prose snippets share many tokens and end up
    with similar vectors — sufficient signal for tests/demos without
    burning OpenAI credits.
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
