"""Builds the dependency bundle needed by the workflow.

Centralizes constructor wiring so API routes don't have to know about
chat models, embeddings, or retrievers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.retrieval.evidence_store import EvidenceStore
from app.retrieval.hybrid_retriever import HybridRetriever
from app.services.models import build_chat_model, build_embeddings

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings
    from langchain_core.language_models.chat_models import BaseChatModel


@dataclass
class WorkflowDeps:
    chat_model: "BaseChatModel"
    embeddings: "Embeddings"
    retriever: HybridRetriever
    evidence_store: EvidenceStore


_singleton: WorkflowDeps | None = None


def get_workflow_deps() -> WorkflowDeps:
    """Lazy-build a process-wide singleton bundle.

    Cheap to construct in mock mode; in real mode this lazily initializes
    the chat-model and embedding clients on first use.
    """
    global _singleton
    if _singleton is None:
        embeddings = build_embeddings()
        chat_model = build_chat_model()
        retriever = HybridRetriever(embeddings=embeddings)
        _singleton = WorkflowDeps(
            chat_model=chat_model,
            embeddings=embeddings,
            retriever=retriever,
            evidence_store=EvidenceStore(),
        )
    return _singleton


def reset_workflow_deps() -> None:
    """Test hook — flushes the singleton so providers can be re-injected."""
    global _singleton
    _singleton = None
