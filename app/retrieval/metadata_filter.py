"""Build SQLAlchemy filter clauses from a research query + retrieval plan."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, or_

from app.db.models import DocumentChunk
from app.schemas.graph_state import RetrievalPlan
from app.schemas.query import ResearchQuery


@dataclass
class MetadataFilter:
    """Encapsulates the WHERE-clause logic so unit tests can introspect it."""

    where: list[ColumnElement] | None = None

    def to_sqlalchemy(self) -> ColumnElement | None:
        if not self.where:
            return None
        return and_(*self.where)

    @classmethod
    def build(
        cls,
        query: ResearchQuery,
        plan: RetrievalPlan | None = None,
    ) -> "MetadataFilter":
        clauses: list[ColumnElement] = []

        if query.ticker:
            clauses.append(DocumentChunk.ticker == query.ticker)
        if query.fiscal_year:
            clauses.append(DocumentChunk.fiscal_year == query.fiscal_year)
        if query.document_type:
            clauses.append(DocumentChunk.document_type == query.document_type.value)
        if query.document_ids:
            clauses.append(DocumentChunk.document_id.in_(query.document_ids))

        if plan:
            if plan.preferred_sections:
                clauses.append(DocumentChunk.section.in_(plan.preferred_sections))
            if plan.preferred_document_types:
                # Override only if user didn't pin a doc type
                if not query.document_type:
                    clauses.append(DocumentChunk.document_type.in_(plan.preferred_document_types))
            if plan.fiscal_years and not query.fiscal_year:
                clauses.append(DocumentChunk.fiscal_year.in_(plan.fiscal_years))

        return cls(where=clauses or None)

    @classmethod
    def relaxed(cls, query: ResearchQuery) -> "MetadataFilter":
        """Same as build() but drops section/content_type/document-type
        constraints — used by the hybrid retriever as a fallback when the
        strict filter returns too few hits.
        """
        clauses: list[ColumnElement] = []
        if query.ticker:
            clauses.append(DocumentChunk.ticker == query.ticker)
        if query.fiscal_year:
            clauses.append(DocumentChunk.fiscal_year == query.fiscal_year)
        if query.document_ids:
            clauses.append(DocumentChunk.document_id.in_(query.document_ids))
        return cls(where=clauses or None)


def section_match_score(plan: RetrievalPlan | None, section: str) -> float:
    """Return [0,1] indicating how well a chunk's section matches the plan."""
    if not plan or not plan.preferred_sections:
        return 0.0
    return 1.0 if section in plan.preferred_sections else 0.0


def content_type_match_score(plan: RetrievalPlan | None, content_type: str) -> float:
    if not plan or not plan.preferred_content_types:
        return 0.0
    return 1.0 if content_type in plan.preferred_content_types else 0.0


def source_priority_score(source_priority: str) -> float:
    """Map source_priority to a [0,1] preference weight."""
    return {
        "primary_filing": 1.0,
        "company_presentation": 0.7,
        "earnings_transcript": 0.7,
        "news": 0.4,
        "other": 0.3,
    }.get(source_priority, 0.5)


def recency_score(filing_year: int | None, today_year: int = 2026) -> float:
    """Newer filings score closer to 1.0; very old ones decay toward 0."""
    if filing_year is None:
        return 0.5
    delta = max(today_year - filing_year, 0)
    return max(0.0, 1.0 - 0.1 * delta)
