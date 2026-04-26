"""Structured research report schema returned by /research/query."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

from .evidence import EvidenceItem
from .query import ResearchIntent

NO_ADVICE_DISCLAIMER = (
    "This prototype summarizes company disclosures and does not provide "
    "investment advice, ratings, or price targets."
)


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Materiality(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class Finding(BaseModel):
    """A single discrete claim in the report, tied to evidence."""

    claim: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.MEDIUM
    reasoning_summary: str | None = None


class FinancialMetric(BaseModel):
    metric_name: str
    period: str | None = None
    value: str | None = None
    change: str | None = None
    source_evidence_ids: list[str] = Field(default_factory=list)


class RiskFactor(BaseModel):
    risk: str
    category: str | None = None
    materiality: Materiality = Materiality.UNKNOWN
    evidence_ids: list[str] = Field(default_factory=list)


class ManagementCommentary(BaseModel):
    topic: str
    quote_or_paraphrase: str
    evidence_ids: list[str] = Field(default_factory=list)


class ResearchReport(BaseModel):
    """Final structured output of the LangGraph workflow."""

    model_config = ConfigDict(from_attributes=True)

    report_id: str
    query: str
    ticker: str | None = None
    company_name: str | None = None
    intent: ResearchIntent

    summary: str
    key_findings: list[Finding] = Field(default_factory=list)
    financial_metrics: list[FinancialMetric] = Field(default_factory=list)
    risk_factors: list[RiskFactor] = Field(default_factory=list)
    management_commentary: list[ManagementCommentary] = Field(default_factory=list)

    evidence: list[EvidenceItem] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)

    no_advice_disclaimer: str = NO_ADVICE_DISCLAIMER
    generated_at: datetime = Field(default_factory=_utcnow)

    def markdown(self) -> str:
        """Render the report as a clean markdown document."""
        lines: list[str] = []
        title_who = self.company_name or self.ticker or "Subject"
        lines.append(f"# Research Summary — {title_who}")
        lines.append("")
        lines.append(f"**Question:** {self.query}")
        lines.append("")
        lines.append(f"**Intent:** `{self.intent.value}`")
        lines.append("")
        lines.append("## Summary")
        lines.append(self.summary)
        lines.append("")

        if self.key_findings:
            lines.append("## Key findings")
            for f in self.key_findings:
                cites = ", ".join(f.evidence_ids) or "—"
                lines.append(f"- **{f.claim}**  ")
                lines.append(f"  _confidence: {f.confidence.value} · evidence: {cites}_")
            lines.append("")

        if self.financial_metrics:
            lines.append("## Financial metrics referenced")
            for m in self.financial_metrics:
                period = f" ({m.period})" if m.period else ""
                value = f" — {m.value}" if m.value else ""
                change = f" Δ {m.change}" if m.change else ""
                lines.append(f"- **{m.metric_name}**{period}{value}{change}")
            lines.append("")

        if self.risk_factors:
            lines.append("## Risk factors disclosed")
            for r in self.risk_factors:
                cat = f" · _{r.category}_" if r.category else ""
                lines.append(f"- **{r.risk}**{cat} (materiality: {r.materiality.value})")
            lines.append("")

        if self.management_commentary:
            lines.append("## Management commentary")
            for c in self.management_commentary:
                lines.append(f"- _{c.topic}_: {c.quote_or_paraphrase}")
            lines.append("")

        if self.limitations:
            lines.append("## Limitations")
            for lim in self.limitations:
                lines.append(f"- {lim}")
            lines.append("")

        if self.validation_warnings:
            lines.append("## Validation warnings")
            for w in self.validation_warnings:
                lines.append(f"- {w}")
            lines.append("")

        lines.append("---")
        lines.append(f"_{self.no_advice_disclaimer}_")
        return "\n".join(lines)
