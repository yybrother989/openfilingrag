"""Routing policies + compliance patterns.

* :data:`INTENT_POLICIES` — what each research intent prefers in terms of
  document types, sections, content types, and term expansions. The
  ``plan_retrieval`` node reads from here to build a :class:`RetrievalPlan`.
* :data:`RESTRICTED_PATTERNS` — language we refuse to generate. Both the
  pre-query guard and the ``validate_report`` node check against these.
* :data:`REFUSAL_MESSAGE` — canonical neutral response for advice questions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas.document import CanonicalSection, ContentType, DocumentType
from app.schemas.query import ResearchIntent

REFUSAL_MESSAGE = (
    "This prototype summarizes company disclosures and does not provide "
    "investment advice, ratings, or price targets."
)

# Patterns indicating the user is asking for advice or that output drifted
# into restricted territory. Matched case-insensitively against query and
# generated text.
RESTRICTED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bbuy (?:this|the) stock\b", re.I),
    re.compile(r"\bsell (?:this|the) stock\b", re.I),
    re.compile(r"\bshould i (?:buy|sell|short|hold)\b", re.I),
    re.compile(r"\b(?:strong )?(?:buy|sell|hold)\s+(?:rating|recommendation)\b", re.I),
    re.compile(r"\bprice target\b", re.I),
    re.compile(r"\btarget price\b", re.I),
    re.compile(r"\bguaranteed return", re.I),
    re.compile(r"\bportfolio allocation recommendation", re.I),
    re.compile(r"\b(?:we|i)\s+(?:\w+\s+)?recommend\s+(?:buying|selling|shorting|holding)\b", re.I),
    re.compile(r"\b(?:will|going\s+to)\s+(?:rise|rally|surge|crash)\b", re.I),
]


def is_advice_query(text: str) -> bool:
    """Return True if the user query is asking for an investment recommendation."""
    return any(p.search(text) for p in RESTRICTED_PATTERNS)


def find_restricted_phrases(text: str) -> list[str]:
    """Return the matched substrings (for validation warnings)."""
    out: list[str] = []
    for p in RESTRICTED_PATTERNS:
        for m in p.finditer(text):
            out.append(m.group(0))
    return out


@dataclass
class RetrievalPolicy:
    """Per-intent routing rules consumed by ``plan_retrieval``."""

    preferred_sections: list[str] = field(default_factory=list)
    preferred_document_types: list[str] = field(default_factory=list)
    preferred_content_types: list[str] = field(default_factory=list)
    metric_expansions: list[str] = field(default_factory=list)
    risk_expansions: list[str] = field(default_factory=list)
    cross_year: bool = False
    table_priority: bool = False
    top_k: int = 12


INTENT_POLICIES: dict[ResearchIntent, RetrievalPolicy] = {
    ResearchIntent.BUSINESS_MODEL: RetrievalPolicy(
        preferred_sections=[
            CanonicalSection.BUSINESS.value,
            CanonicalSection.SEGMENT_INFORMATION.value,
        ],
        preferred_document_types=[DocumentType.TEN_K.value, DocumentType.ANNUAL_REPORT.value],
        preferred_content_types=[
            ContentType.BUSINESS_OVERVIEW.value,
            ContentType.SEGMENT.value,
        ],
        metric_expansions=["revenue", "segment"],
        top_k=10,
    ),
    ResearchIntent.REVENUE_DRIVERS: RetrievalPolicy(
        preferred_sections=[
            CanonicalSection.MDA.value,
            CanonicalSection.SEGMENT_INFORMATION.value,
            CanonicalSection.BUSINESS.value,
        ],
        preferred_document_types=[
            DocumentType.TEN_K.value,
            DocumentType.TEN_Q.value,
            DocumentType.ANNUAL_REPORT.value,
        ],
        preferred_content_types=[
            ContentType.MDA.value,
            ContentType.SEGMENT.value,
        ],
        metric_expansions=["revenue", "segment", "guidance"],
        table_priority=True,
        top_k=14,
    ),
    ResearchIntent.MARGIN_ANALYSIS: RetrievalPolicy(
        preferred_sections=[
            CanonicalSection.MDA.value,
            CanonicalSection.FINANCIAL_STATEMENTS.value,
            CanonicalSection.NOTES_TO_FINANCIAL.value,
            CanonicalSection.SEGMENT_INFORMATION.value,
        ],
        preferred_document_types=[
            DocumentType.TEN_K.value,
            DocumentType.TEN_Q.value,
        ],
        preferred_content_types=[
            ContentType.MDA.value,
            ContentType.FINANCIAL_STATEMENT.value,
            ContentType.SEGMENT.value,
        ],
        metric_expansions=[
            "gross_margin",
            "operating_margin",
            "rd_expense",
            "sga",
        ],
        table_priority=True,
        top_k=14,
    ),
    ResearchIntent.RISK_ANALYSIS: RetrievalPolicy(
        preferred_sections=[
            CanonicalSection.RISK_FACTORS.value,
            CanonicalSection.LEGAL_PROCEEDINGS.value,
            CanonicalSection.MDA.value,
        ],
        preferred_document_types=[
            DocumentType.TEN_K.value,
            DocumentType.TEN_Q.value,
            DocumentType.ANNUAL_REPORT.value,
        ],
        preferred_content_types=[ContentType.RISK_FACTOR.value],
        risk_expansions=list(
            (
                "macroeconomic competition regulation litigation supply_chain "
                "fx cybersecurity concentration dependency ip geopolitical climate talent"
            ).split()
        ),
        top_k=16,
    ),
    ResearchIntent.LIQUIDITY_ANALYSIS: RetrievalPolicy(
        preferred_sections=[
            CanonicalSection.LIQUIDITY.value,
            CanonicalSection.FINANCIAL_STATEMENTS.value,
            CanonicalSection.NOTES_TO_FINANCIAL.value,
            CanonicalSection.MDA.value,
        ],
        preferred_document_types=[
            DocumentType.TEN_K.value,
            DocumentType.TEN_Q.value,
        ],
        preferred_content_types=[
            ContentType.MDA.value,
            ContentType.FINANCIAL_STATEMENT.value,
        ],
        metric_expansions=["cash_flow", "debt", "liquidity", "capex", "buyback", "dividend"],
        table_priority=True,
        top_k=14,
    ),
    ResearchIntent.MANAGEMENT_OUTLOOK: RetrievalPolicy(
        preferred_sections=[
            CanonicalSection.MDA.value,
            CanonicalSection.OUTLOOK.value,
        ],
        preferred_document_types=[
            DocumentType.TEN_K.value,
            DocumentType.TEN_Q.value,
            DocumentType.EARNINGS_TRANSCRIPT.value,
            DocumentType.INVESTOR_PRESENTATION.value,
        ],
        preferred_content_types=[ContentType.MDA.value, ContentType.OUTLOOK.value],
        metric_expansions=["guidance"],
        top_k=10,
    ),
    ResearchIntent.CROSS_YEAR_COMPARISON: RetrievalPolicy(
        preferred_sections=[
            CanonicalSection.RISK_FACTORS.value,
            CanonicalSection.MDA.value,
            CanonicalSection.SEGMENT_INFORMATION.value,
            CanonicalSection.LIQUIDITY.value,
        ],
        preferred_document_types=[DocumentType.TEN_K.value, DocumentType.ANNUAL_REPORT.value],
        cross_year=True,
        top_k=20,
    ),
    ResearchIntent.SEGMENT_ANALYSIS: RetrievalPolicy(
        preferred_sections=[
            CanonicalSection.SEGMENT_INFORMATION.value,
            CanonicalSection.MDA.value,
        ],
        preferred_document_types=[DocumentType.TEN_K.value, DocumentType.TEN_Q.value],
        preferred_content_types=[ContentType.SEGMENT.value, ContentType.MDA.value],
        metric_expansions=["segment", "revenue"],
        table_priority=True,
        top_k=12,
    ),
    ResearchIntent.FINANCIAL_STATEMENT_LOOKUP: RetrievalPolicy(
        preferred_sections=[
            CanonicalSection.FINANCIAL_STATEMENTS.value,
            CanonicalSection.NOTES_TO_FINANCIAL.value,
        ],
        preferred_document_types=[DocumentType.TEN_K.value, DocumentType.TEN_Q.value],
        preferred_content_types=[ContentType.FINANCIAL_STATEMENT.value, ContentType.TABLE.value],
        table_priority=True,
        top_k=10,
    ),
    ResearchIntent.GENERIC_FILING_QA: RetrievalPolicy(
        top_k=12,
    ),
}


def get_policy(intent: ResearchIntent) -> RetrievalPolicy:
    return INTENT_POLICIES.get(intent, INTENT_POLICIES[ResearchIntent.GENERIC_FILING_QA])
