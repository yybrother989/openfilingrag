"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from app.services.mock_chat_model import MockChatModel
from app.services.mock_embeddings import HashEmbeddings


@pytest.fixture
def mock_embedding() -> HashEmbeddings:
    """LangChain Embeddings — small dim so tests stay fast."""
    return HashEmbeddings(dim=128)


@pytest.fixture
def mock_chat_model() -> MockChatModel:
    """Chat model that only honours .with_structured_output(schema)."""
    return MockChatModel()
