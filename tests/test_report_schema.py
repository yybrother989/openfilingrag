"""Pydantic validation of the public report contract."""

from __future__ import annotations

import uuid

from app.schemas.evidence import EvidenceItem
from app.schemas.query import ResearchIntent
from app.schemas.report import (
    NO_ADVICE_DISCLAIMER,
    Confidence,
    Finding,
    FinancialMetric,
    ManagementCommentary,
    Materiality,
    ResearchReport,
    RiskFactor,
)
from app.schemas.document import (
    ContentType,
    DocumentType,
    SourcePriority,
)


def _ev() -> EvidenceItem:
    return EvidenceItem(
        source_id=str(uuid.uuid4()),
        document_id=1,
        ticker="ACME",
        document_type=DocumentType.TEN_K,
        section="Risk Factors",
        content_type=ContentType.RISK_FACTOR,
        text="snippet",
        relevance_score=0.5,
        source_priority=SourcePriority.PRIMARY_FILING,
    )


def test_report_serializes_round_trip() -> None:
    ev = _ev()
    rep = ResearchReport(
        report_id=str(uuid.uuid4()),
        query="What risks?",
        ticker="ACME",
        company_name="Acme Corp",
        intent=ResearchIntent.RISK_ANALYSIS,
        summary="Summary text.",
        key_findings=[
            Finding(
                claim="Macroeconomic risk is highlighted.",
                evidence_ids=[ev.source_id],
                confidence=Confidence.HIGH,
            )
        ],
        financial_metrics=[
            FinancialMetric(
                metric_name="revenue",
                period="FY2025",
                value="2400",
                change="+6.2%",
                source_evidence_ids=[ev.source_id],
            )
        ],
        risk_factors=[
            RiskFactor(
                risk="Inflation risk",
                category="macroeconomic",
                materiality=Materiality.MEDIUM,
                evidence_ids=[ev.source_id],
            )
        ],
        management_commentary=[
            ManagementCommentary(
                topic="liquidity",
                quote_or_paraphrase="Strong cash position.",
                evidence_ids=[ev.source_id],
            )
        ],
        evidence=[ev],
        limitations=["Mock-mode synthesis."],
    )
    payload = rep.model_dump(mode="json")
    rebuilt = ResearchReport.model_validate(payload)
    assert rebuilt.report_id == rep.report_id
    assert rebuilt.no_advice_disclaimer == NO_ADVICE_DISCLAIMER
    md = rep.markdown()
    assert "Research Summary" in md
    assert NO_ADVICE_DISCLAIMER in md


def test_finding_defaults_confidence_medium() -> None:
    f = Finding(claim="X")
    assert f.confidence == Confidence.MEDIUM
    assert f.evidence_ids == []
