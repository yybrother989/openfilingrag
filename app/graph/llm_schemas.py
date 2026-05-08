"""LLM-facing Pydantic schemas — what the chat model is asked to fill.

Kept separate from the public :class:`ResearchReport` so:

  * the LLM sees a smaller schema (no ``report_id`` / ``evidence`` /
    ``generated_at`` etc. that get filled server-side),
  * citations use **one-based numbers** that map back to evidence
    chunks (LlamaIndex CitationQueryEngine pattern), and
  * the public report stays the same shape it has always been.

The graph's ``generate_report`` node passes one of these schemas to
``chat_model.with_structured_output(...)``. ``_build_research_report``
then translates ``evidence_numbers`` to project-stable
``source_id`` strings.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.query import ResearchIntent
from app.schemas.report import Confidence, Materiality


class LLMClassifyOutput(BaseModel):
    """Structured output of the classify_query node."""

    intent: ResearchIntent = Field(
        description="One of the canonical research intents."
    )
    ticker: str | None = Field(default=None, description="Uppercase ticker symbol or null.")
    company_name: str | None = Field(default=None)
    fiscal_year: int | None = Field(default=None)
    wants_cross_year: bool = Field(
        default=False,
        description="True iff the question explicitly compares multiple fiscal years.",
    )


class LLMFinding(BaseModel):
    """One claim in key_findings.

    ``evidence_numbers`` is REQUIRED — at least one number must be
    supplied or the validate node will reject the draft and trigger
    self-correction.
    """

    claim: str
    evidence_numbers: list[int] = Field(
        default_factory=list,
        description=(
            "One-based citation numbers from the supplied citation chunks. "
            "Each finding MUST cite at least one number. Do not invent numbers."
        ),
    )
    confidence: Confidence = Confidence.MEDIUM
    reasoning_summary: str | None = None


class LLMFinancialMetric(BaseModel):
    metric_name: str
    period: str | None = None
    value: str | None = None
    change: str | None = None
    evidence_numbers: list[int] = Field(default_factory=list)


class LLMRiskFactor(BaseModel):
    risk: str
    category: str | None = None
    materiality: Materiality = Materiality.UNKNOWN
    evidence_numbers: list[int] = Field(default_factory=list)


class LLMManagementCommentary(BaseModel):
    topic: str
    quote_or_paraphrase: str
    evidence_numbers: list[int] = Field(default_factory=list)


class LLMReportDraft(BaseModel):
    """Structured draft of the research report.

    The Python side fills the public :class:`ResearchReport` from this:

      - assigns a fresh ``report_id``
      - attaches the retrieved ``evidence`` list
      - adds ``generated_at`` and ``no_advice_disclaimer``
      - translates every ``evidence_numbers: list[int]`` to
        ``evidence_ids: list[str]`` via the citation number map
    """

    summary: str = Field(description="3–6 sentence overview answering the question.")
    key_findings: list[LLMFinding] = Field(default_factory=list)
    financial_metrics: list[LLMFinancialMetric] = Field(default_factory=list)
    risk_factors: list[LLMRiskFactor] = Field(default_factory=list)
    management_commentary: list[LLMManagementCommentary] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
