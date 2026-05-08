"""Chat-model and embedding factories.

Replaces the deleted ``LLMService`` / ``EmbeddingService`` facades. Wraps
``langchain.chat_models.init_chat_model`` and ``langchain.embeddings.
init_embeddings`` so the rest of the project sees plain LangChain
``BaseChatModel`` / ``Embeddings`` objects.

Mock-mode fallback: returns :class:`MockChatModel` and
:class:`HashEmbeddings` when the project is in mock mode (no API keys).
"""

from __future__ import annotations

import os

from langchain.chat_models import init_chat_model
from langchain.embeddings import init_embeddings
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import settings
from app.core.logging import get_logger

from .mock_chat_model import MockChatModel
from .mock_embeddings import HashEmbeddings

log = get_logger(__name__)


def build_chat_model() -> BaseChatModel:
    """Return a ready-to-use chat model.

    In mock mode (no API keys) returns ``MockChatModel``. Otherwise
    routes to the configured provider via :func:`init_chat_model`.
    """
    if settings.is_mock_mode:
        log.info("chat model: mock")
        return MockChatModel()
    _bridge_api_keys_to_env()
    spec = _provider_spec()
    log.info("chat model: %s", spec)
    return init_chat_model(spec, temperature=0.0)


def build_embeddings() -> Embeddings:
    """Return a ready-to-use embeddings model.

    Mock-mode → :class:`HashEmbeddings`. Otherwise OpenAI via
    :func:`init_embeddings`.
    """
    if settings.effective_embedding_provider == "hash":
        log.info("embeddings: hash (mock)")
        return HashEmbeddings(dim=settings.pgvector_dim)
    _bridge_api_keys_to_env()
    model = settings.embedding_model or "text-embedding-3-small"
    log.info("embeddings: openai:%s", model)
    return init_embeddings(f"openai:{model}")


def _provider_spec() -> str:
    name = settings.effective_llm_provider  # "openai" | "anthropic"
    default_model = {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-haiku-4-5",
    }[name]
    model = settings.llm_model or default_model
    return f"{name}:{model}"


def _bridge_api_keys_to_env() -> None:
    """``init_chat_model`` reads ``OPENAI_API_KEY`` / ``ANTHROPIC_API_KEY``
    from ``os.environ`` directly. Pydantic-settings populates ``settings``
    from .env but does NOT propagate to ``os.environ``, so we copy them
    over here just-in-time so the LangChain integrations pick them up."""
    if settings.openai_api_key and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    if settings.anthropic_api_key and not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
