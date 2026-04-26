"""Builds the dependency bundle needed by the workflow.

Centralizes constructor wiring so API routes don't have to know about
``EmbeddingService``, ``LLMService``, ``HybridRetriever``, etc.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.retrieval.evidence_store import EvidenceStore
from app.retrieval.hybrid_retriever import HybridRetriever
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService


@dataclass
class WorkflowDeps:
    llm: LLMService
    embedding: EmbeddingService
    retriever: HybridRetriever
    evidence_store: EvidenceStore


_singleton: WorkflowDeps | None = None


def get_workflow_deps() -> WorkflowDeps:
    """Lazy-build a process-wide singleton bundle.

    Cheap to construct in mock mode; in real mode this lazily initializes
    the LLM and embedding clients on first use.
    """
    global _singleton
    if _singleton is None:
        embedding = EmbeddingService()
        llm = LLMService()
        retriever = HybridRetriever(embedding_service=embedding)
        evidence_store = EvidenceStore()
        _singleton = WorkflowDeps(
            llm=llm,
            embedding=embedding,
            retriever=retriever,
            evidence_store=evidence_store,
        )
    return _singleton


def reset_workflow_deps() -> None:
    """Test hook — flushes the singleton so providers can be re-injected."""
    global _singleton
    _singleton = None
