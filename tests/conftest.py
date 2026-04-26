"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from app.services.embedding_service import EmbeddingService, HashEmbedder
from app.services.llm_service import LLMService, MockProvider


@pytest.fixture
def mock_embedding() -> EmbeddingService:
    return EmbeddingService(embedder=HashEmbedder(dim=128))


@pytest.fixture
def mock_llm() -> LLMService:
    return LLMService(provider=MockProvider())
