"""Factory functions in :mod:`app.services.models`."""

from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel

from app.services.mock_chat_model import MockChatModel
from app.services.mock_embeddings import HashEmbeddings
from app.services.models import build_chat_model, build_embeddings


def test_mock_mode_returns_mock_chat_model(monkeypatch) -> None:
    """When no API keys are set the factory must return a MockChatModel."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    monkeypatch.setattr(settings, "llm_provider", None)
    monkeypatch.setattr(settings, "embedding_provider", None)

    chat = build_chat_model()
    emb = build_embeddings()

    assert isinstance(chat, BaseChatModel)
    assert isinstance(chat, MockChatModel)

    assert isinstance(emb, Embeddings)
    assert isinstance(emb, HashEmbeddings)


def test_mock_chat_model_supports_structured_output_only() -> None:
    """Sanity: the mock raises on free-text generation but accepts
    .with_structured_output(...)."""
    from app.graph.llm_schemas import LLMClassifyOutput

    mock = MockChatModel()
    out = mock.with_structured_output(LLMClassifyOutput).invoke(
        [{"role": "user", "content": "What are the main risks for AAPL?"}]
    )
    assert out.intent.value == "risk_analysis"
