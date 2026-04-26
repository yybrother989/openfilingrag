"""Metadata filter must produce the expected SQL clauses."""

from __future__ import annotations

from sqlalchemy.dialects import postgresql

from app.retrieval.metadata_filter import (
    MetadataFilter,
    recency_score,
    section_match_score,
    source_priority_score,
)
from app.schemas.document import CanonicalSection, DocumentType
from app.schemas.graph_state import RetrievalPlan
from app.schemas.query import ResearchIntent, ResearchQuery


def _compile(clause) -> str:
    return str(
        clause.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_ticker_year_doctype_constraints_present() -> None:
    q = ResearchQuery(
        query="What is the company's risk profile?",
        ticker="acme",
        fiscal_year=2025,
        document_type=DocumentType.TEN_K,
        document_ids=[9, 2, 9],
    )
    where = MetadataFilter.build(q).to_sqlalchemy()
    assert where is not None
    rendered = _compile(where).lower()
    assert "ticker = 'acme'" in rendered
    assert "fiscal_year = 2025" in rendered
    assert "document_type = '10-k'" in rendered
    assert "document_id in (2, 9)" in rendered


def test_plan_adds_section_filter() -> None:
    q = ResearchQuery(query="risks", ticker="ACME")
    plan = RetrievalPlan(
        intent=ResearchIntent.RISK_ANALYSIS,
        preferred_sections=[CanonicalSection.RISK_FACTORS.value],
    )
    where = MetadataFilter.build(q, plan).to_sqlalchemy()
    rendered = _compile(where).lower()
    assert "in ('risk factors')" in rendered or "in ('risk factors'::" in rendered


def test_relaxed_drops_section_filter() -> None:
    q = ResearchQuery(query="risks", ticker="ACME")
    relaxed = MetadataFilter.relaxed(q).to_sqlalchemy()
    assert relaxed is not None
    rendered = _compile(relaxed).lower()
    assert "section" not in rendered


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
