"""LangGraph workflow state — passed between nodes by reference."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .evidence import EvidenceItem
from .query import ResearchIntent, ResearchQuery
from .report import ResearchReport


class RetrievalPlan(BaseModel):
    """Output of the plan_retrieval node — what to fetch and how to filter."""

    intent: ResearchIntent
    preferred_sections: list[str] = Field(default_factory=list)
    preferred_document_types: list[str] = Field(default_factory=list)
    preferred_content_types: list[str] = Field(default_factory=list)
    metric_expansions: list[str] = Field(default_factory=list)
    risk_expansions: list[str] = Field(default_factory=list)
    cross_year: bool = False
    table_priority: bool = False
    top_k: int = 12
    fiscal_years: list[int] = Field(default_factory=list)
    expanded_query: str | None = None


class GraphState(BaseModel):
    """Shared state object threaded through every LangGraph node.

    Nodes receive a copy and return an updated copy. Treat as immutable
    within a single node.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_query: ResearchQuery
    intent: ResearchIntent | None = None
    ticker: str | None = None
    company_name: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)

    retrieval_plan: RetrievalPlan | None = None
    evidence_items: list[EvidenceItem] = Field(default_factory=list)

    draft_report: ResearchReport | None = None
    final_report: ResearchReport | None = None

    validation_warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    # Workflow bookkeeping
    revision_count: int = 0
    refused: bool = False
