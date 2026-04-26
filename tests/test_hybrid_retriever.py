"""Hybrid retriever fusion logic, exercised against in-memory stub stores."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from app.retrieval.hybrid_retriever import HybridRetriever
from app.schemas.document import (
    CanonicalSection,
    ContentType,
    DocumentType,
    SourcePriority,
)
from app.schemas.evidence import EvidenceItem
from app.schemas.graph_state import RetrievalPlan
from app.schemas.query import ResearchIntent, ResearchQuery


@dataclass
class FakeChunk:
    """Quacks like ``app.db.models.DocumentChunk`` for the retriever's purposes."""

    id: int
    source_id: uuid.UUID
    document_id: int
    chunk_index: int
    ticker: str
    company_name: str
    document_type: str
    fiscal_year: int | None
    filing_date: None
    source_priority: str
    section: str
    subsection: str | None
    content_type: str
    page_start: int | None
    page_end: int | None
    chunk_text: str
    metric_tags: list[str]
    risk_tags: list[str]


def _chunk(
    cid: int, section: str, text: str, score: float = 0.7
) -> tuple[FakeChunk, float]:
    chunk = FakeChunk(
        id=cid,
        source_id=uuid.uuid4(),
        document_id=1,
        chunk_index=cid,
        ticker="ACME",
        company_name="Acme Corp",
        document_type=DocumentType.TEN_K.value,
        fiscal_year=2025,
        filing_date=None,
        source_priority=SourcePriority.PRIMARY_FILING.value,
        section=section,
        subsection=None,
        content_type=ContentType.RISK_FACTOR.value
        if section == CanonicalSection.RISK_FACTORS.value
        else ContentType.PARAGRAPH.value,
        page_start=10,
        page_end=11,
        chunk_text=text,
        metric_tags=[],
        risk_tags=["macroeconomic"] if "macroeconomic" in text else [],
    )
    return chunk, score


class _StubVector:
    def __init__(self, hits: list[tuple[FakeChunk, float]]):
        self._hits = hits

    def search(self, session, embedding, where=None, k=50):  # noqa: D401, ARG002
        return self._hits


class _StubKeyword:
    def __init__(self, hits: list[tuple[FakeChunk, float]]):
        self._hits = hits

    def search(self, session, query, where=None, k=50):  # noqa: D401, ARG002
        return self._hits


def test_returns_evidence_items_with_scores(mock_embedding) -> None:
    risk = _chunk(1, CanonicalSection.RISK_FACTORS.value, "macroeconomic risk discussion", 0.9)
    business = _chunk(2, CanonicalSection.BUSINESS.value, "company makes widgets", 0.4)
    retriever = HybridRetriever(
        embedding_service=mock_embedding,
        vector_store=_StubVector([risk, business]),
        keyword_search=_StubKeyword([risk]),
    )
    plan = RetrievalPlan(
        intent=ResearchIntent.RISK_ANALYSIS,
        preferred_sections=[CanonicalSection.RISK_FACTORS.value],
        top_k=5,
    )
    items = retriever.retrieve(
        session=None,
        query=ResearchQuery(query="What risks?", ticker="ACME"),
        plan=plan,
    )
    assert len(items) > 0
    assert all(isinstance(e, EvidenceItem) for e in items)
    # Risk-section chunk should outrank business with a risk-analysis plan
    assert items[0].section == CanonicalSection.RISK_FACTORS.value
    assert items[0].relevance_score > items[-1].relevance_score


def test_fallback_to_relaxed_filter(mock_embedding) -> None:
    """When strict filter returns nothing, retriever should still degrade."""
    retriever = HybridRetriever(
        embedding_service=mock_embedding,
        vector_store=_StubVector([]),
        keyword_search=_StubKeyword([]),
    )
    items = retriever.retrieve(
        session=None,
        query=ResearchQuery(query="risks", ticker="ACME"),
        plan=RetrievalPlan(intent=ResearchIntent.RISK_ANALYSIS, top_k=5),
    )
    assert items == []  # no data at all → empty, not exception


@pytest.mark.parametrize("section", [
    CanonicalSection.MDA.value,
    CanonicalSection.RISK_FACTORS.value,
])
def test_score_breakdown_present(section, mock_embedding) -> None:
    hit = _chunk(1, section, "some text", 0.5)
    retriever = HybridRetriever(
        embedding_service=mock_embedding,
        vector_store=_StubVector([hit]),
        keyword_search=_StubKeyword([]),
    )
    items = retriever.retrieve(
        session=None,
        query=ResearchQuery(query="anything", ticker="ACME"),
        plan=RetrievalPlan(intent=ResearchIntent.GENERIC_FILING_QA),
    )
    assert items[0].score_breakdown is not None
    assert {"vector", "keyword", "section", "source", "recency"} <= items[0].score_breakdown.keys()
