"""MetadataFilter must produce the expected PGVector dict filter."""

from __future__ import annotations

from app.retrieval.metadata_filter import (
    MetadataFilter,
    recency_score,
    section_match_score,
    source_priority_score,
)
from app.schemas.document import CanonicalSection, DocumentType
from app.schemas.graph_state import RetrievalPlan
from app.schemas.query import ResearchIntent, ResearchQuery


def _flatten(filt: dict | None) -> list[dict]:
    """Return the leaf clauses regardless of $and wrapping."""
    if filt is None:
        return []
    if "$and" in filt:
        return list(filt["$and"])
    return [filt]


def test_ticker_year_doctype_constraints_present() -> None:
    q = ResearchQuery(
        query="What is the company's risk profile?",
        ticker="acme",
        fiscal_year=2025,
        document_type=DocumentType.TEN_K,
        document_ids=[9, 2, 9],
    )
    where = MetadataFilter.build(q).to_pgvector_filter()
    assert where is not None
    leaves = _flatten(where)
    # ResearchQuery normalizes ticker to uppercase
    assert {"ticker": {"$eq": "ACME"}} in leaves
    assert {"fiscal_year": {"$eq": 2025}} in leaves
    assert {"document_type": {"$eq": "10-K"}} in leaves
    # Pydantic dedupes/sorts document_ids before reaching MetadataFilter
    doc_ids_clause = next(c for c in leaves if "document_id" in c)
    assert sorted(doc_ids_clause["document_id"]["$in"]) == [2, 9]


def test_plan_adds_section_filter() -> None:
    q = ResearchQuery(query="risks", ticker="ACME")
    plan = RetrievalPlan(
        intent=ResearchIntent.RISK_ANALYSIS,
        preferred_sections=[CanonicalSection.RISK_FACTORS.value],
    )
    where = MetadataFilter.build(q, plan).to_pgvector_filter()
    leaves = _flatten(where)
    assert {"section": {"$in": ["Risk Factors"]}} in leaves


def test_relaxed_drops_section_filter() -> None:
    q = ResearchQuery(query="risks", ticker="ACME")
    relaxed = MetadataFilter.relaxed(q).to_pgvector_filter()
    assert relaxed is not None
    # No section / document_type clauses
    leaves = _flatten(relaxed)
    keys = {next(iter(leaf)) for leaf in leaves}
    assert "section" not in keys
    assert "document_type" not in keys
    assert "ticker" in keys


def test_section_match_scoring() -> None:
    plan = RetrievalPlan(
        intent=ResearchIntent.RISK_ANALYSIS,
        preferred_sections=[CanonicalSection.RISK_FACTORS.value],
    )
    assert section_match_score(plan, CanonicalSection.RISK_FACTORS.value) == 1.0
    assert section_match_score(plan, CanonicalSection.MDA.value) == 0.0
    assert section_match_score(None, "anything") == 0.0


def test_priority_and_recency_scores() -> None:
    assert source_priority_score("primary_filing") == 1.0
    assert source_priority_score("news") < source_priority_score("primary_filing")
    assert recency_score(2026, today_year=2026) == 1.0
    assert recency_score(2020, today_year=2026) < 1.0
    assert recency_score(None) == 0.5
