"""Hybrid retriever fusion logic, exercised against in-memory stubs.

The retriever now talks to LangChain ``Document`` lists (PGVector +
PGFTSRetriever output shape). We bypass the real Postgres backends with
``vector_store=`` and ``fts_retriever=`` injection.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from langchain_core.documents import Document

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


def _doc(section: str, text: str) -> Document:
    return Document(
        page_content=text,
        metadata={
            "source_id": str(uuid.uuid4()),
            "document_id": 1,
            "chunk_index": 0,
            "ticker": "ACME",
            "company_name": "Acme Corp",
            "document_type": DocumentType.TEN_K.value,
            "fiscal_year": 2025,
            "filing_date": None,
            "source_priority": SourcePriority.PRIMARY_FILING.value,
            "section": section,
            "content_type": (
                ContentType.RISK_FACTOR.value
                if section == CanonicalSection.RISK_FACTORS.value
                else ContentType.PARAGRAPH.value
            ),
            "page_start": 10,
            "page_end": 11,
            "metric_tags": [],
            "risk_tags": ["macroeconomic"] if "macroeconomic" in text else [],
        },
    )


@dataclass
class _StubVectorStore:
    """Quacks like ``langchain_postgres.PGVector`` for the retriever's call site."""

    docs: list[Document]

    def similarity_search(self, query, k=4, filter=None):  # noqa: ARG002
        return list(self.docs)


@dataclass
class _StubFTSRetriever:
    docs: list[Document]

    def invoke(self, query):  # noqa: ARG002
        return list(self.docs)


def test_returns_evidence_items_with_scores(mock_embedding) -> None:
    risk = _doc(CanonicalSection.RISK_FACTORS.value, "macroeconomic risk discussion")
    business = _doc(CanonicalSection.BUSINESS.value, "company makes widgets")
    retriever = HybridRetriever(
        embeddings=mock_embedding,
        vector_store=_StubVectorStore([risk, business]),
        fts_retriever=_StubFTSRetriever([risk]),
    )
    plan = RetrievalPlan(
        intent=ResearchIntent.RISK_ANALYSIS,
        preferred_sections=[CanonicalSection.RISK_FACTORS.value],
        top_k=5,
    )
    items = retriever.retrieve(
        query=ResearchQuery(query="What risks?", ticker="ACME"),
        plan=plan,
    )
    assert len(items) > 0
    assert all(isinstance(e, EvidenceItem) for e in items)
    # Risk-section chunk should outrank business with a risk-analysis plan
    assert items[0].section == CanonicalSection.RISK_FACTORS.value
    assert items[0].relevance_score > items[-1].relevance_score


def test_fallback_returns_empty_when_no_data(mock_embedding) -> None:
    """When neither leg returns hits and the relaxed retry also returns
    empty, the retriever degrades to an empty list rather than raising.
    """
    retriever = HybridRetriever(
        embeddings=mock_embedding,
        vector_store=_StubVectorStore([]),
        fts_retriever=_StubFTSRetriever([]),
    )
    items = retriever.retrieve(
        query=ResearchQuery(query="risks", ticker="ACME"),
        plan=RetrievalPlan(intent=ResearchIntent.RISK_ANALYSIS, top_k=5),
    )
    assert items == []


@pytest.mark.parametrize("section", [
    CanonicalSection.MDA.value,
    CanonicalSection.RISK_FACTORS.value,
])
def test_score_breakdown_present(section, mock_embedding) -> None:
    hit = _doc(section, "some text")
    retriever = HybridRetriever(
        embeddings=mock_embedding,
        vector_store=_StubVectorStore([hit]),
        fts_retriever=_StubFTSRetriever([]),
    )
    items = retriever.retrieve(
        query=ResearchQuery(query="anything", ticker="ACME"),
        plan=RetrievalPlan(intent=ResearchIntent.GENERIC_FILING_QA),
    )
    assert items[0].score_breakdown is not None
    assert {"vector", "keyword", "section", "source", "recency"} <= items[0].score_breakdown.keys()
