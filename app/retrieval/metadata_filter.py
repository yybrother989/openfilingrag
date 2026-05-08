"""Build a PGVector-compatible filter dict from a research query + plan.

Output shape uses PGVector's documented operators (use_jsonb=True):

    {"$and": [
        {"ticker":        {"$eq":  "AAPL"}},
        {"fiscal_year":   {"$eq":  2024}},
        {"document_type": {"$in":  ["10-K", "10-Q"]}},
        {"section":       {"$in":  ["Risk Factors", "MD&A"]}},
    ]}

Both :class:`langchain_postgres.PGVector` and our
:class:`PGFTSRetriever` accept this same dict shape, so the hybrid
retriever can pass one filter to both legs.

The score helpers below return ``[0,1]`` weights consumed by
:class:`HybridRetriever` after fusion — they're not part of the SQL
filter, just secondary signals layered onto the RRF text score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.graph_state import RetrievalPlan
from app.schemas.query import ResearchQuery


@dataclass
class MetadataFilter:
    clauses: list[dict[str, Any]] = field(default_factory=list)

    def to_pgvector_filter(self) -> dict[str, Any] | None:
        if not self.clauses:
            return None
        if len(self.clauses) == 1:
            return self.clauses[0]
        return {"$and": list(self.clauses)}

    @classmethod
    def build(
        cls,
        query: ResearchQuery,
        plan: RetrievalPlan | None = None,
    ) -> "MetadataFilter":
        clauses: list[dict[str, Any]] = []

        if query.ticker:
            clauses.append({"ticker": {"$eq": query.ticker}})
        if query.fiscal_year:
            clauses.append({"fiscal_year": {"$eq": query.fiscal_year}})
        if query.document_type:
            clauses.append({"document_type": {"$eq": query.document_type.value}})
        if query.document_ids:
            clauses.append({"document_id": {"$in": list(query.document_ids)}})

        if plan:
            if plan.preferred_sections:
                clauses.append({"section": {"$in": list(plan.preferred_sections)}})
            if plan.preferred_document_types and not query.document_type:
                clauses.append(
                    {"document_type": {"$in": list(plan.preferred_document_types)}}
                )
            if plan.fiscal_years and not query.fiscal_year:
                clauses.append({"fiscal_year": {"$in": list(plan.fiscal_years)}})

        return cls(clauses=clauses)

    @classmethod
    def relaxed(cls, query: ResearchQuery) -> "MetadataFilter":
        """Same as build() but drops section / document-type / plan
        constraints. Used by HybridRetriever as a fallback when the
        strict filter returns no hits.
        """
        clauses: list[dict[str, Any]] = []
        if query.ticker:
            clauses.append({"ticker": {"$eq": query.ticker}})
        if query.fiscal_year:
            clauses.append({"fiscal_year": {"$eq": query.fiscal_year}})
        if query.document_ids:
            clauses.append({"document_id": {"$in": list(query.document_ids)}})
        return cls(clauses=clauses)


# ---- secondary scoring signals (consumed after RRF fusion) ------------

def section_match_score(plan: RetrievalPlan | None, section: str) -> float:
    if not plan or not plan.preferred_sections:
        return 0.0
    return 1.0 if section in plan.preferred_sections else 0.0


def content_type_match_score(plan: RetrievalPlan | None, content_type: str) -> float:
    if not plan or not plan.preferred_content_types:
        return 0.0
    return 1.0 if content_type in plan.preferred_content_types else 0.0


def source_priority_score(source_priority: str) -> float:
    return {
        "primary_filing": 1.0,
        "company_presentation": 0.7,
        "earnings_transcript": 0.7,
        "news": 0.4,
        "other": 0.3,
    }.get(source_priority, 0.5)


def recency_score(filing_year: int | None, today_year: int = 2026) -> float:
    if filing_year is None:
        return 0.5
    delta = max(today_year - filing_year, 0)
    return max(0.0, 1.0 - 0.1 * delta)
