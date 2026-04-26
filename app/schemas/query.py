"""Inbound research query schema + research intents."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator

from .document import DocumentType


class ResearchIntent(str, Enum):
    """High-level routing categories for incoming research questions."""

    BUSINESS_MODEL = "business_model"
    REVENUE_DRIVERS = "revenue_drivers"
    MARGIN_ANALYSIS = "margin_analysis"
    RISK_ANALYSIS = "risk_analysis"
    LIQUIDITY_ANALYSIS = "liquidity_analysis"
    MANAGEMENT_OUTLOOK = "management_outlook"
    CROSS_YEAR_COMPARISON = "cross_year_comparison"
    SEGMENT_ANALYSIS = "segment_analysis"
    FINANCIAL_STATEMENT_LOOKUP = "financial_statement_lookup"
    GENERIC_FILING_QA = "generic_filing_qa"
    REFUSED_ADVICE = "refused_advice"  # produced by compliance guard


class ResearchQuery(BaseModel):
    """Inbound /research/query payload."""

    query: str = Field(..., min_length=2, max_length=2000)
    ticker: str | None = None
    company_name: str | None = None
    fiscal_year: int | None = None
    document_type: DocumentType | None = None
    document_ids: list[int] = Field(default_factory=list)
    top_k: int | None = Field(default=None, ge=1, le=50)

    @field_validator("ticker")
    @classmethod
    def _upper_ticker(cls, v: str | None) -> str | None:
        return v.upper() if v else v

    @field_validator("document_ids")
    @classmethod
    def _normalize_document_ids(cls, value: list[int]) -> list[int]:
        return sorted({doc_id for doc_id in value if doc_id > 0})
