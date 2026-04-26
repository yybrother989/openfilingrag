"""Lightweight evaluation helpers for the prototype.

These metrics are deliberately simple — designed for sanity-checks during
development, not as a substitute for a real RAG-evaluation framework.
"""

from __future__ import annotations

from app.schemas.evidence import EvidenceItem
from app.schemas.report import ResearchReport


def evidence_grounding_ratio(report: ResearchReport) -> float:
    """Fraction of key findings that cite at least one valid evidence_id."""
    if not report.key_findings:
        return 0.0
    valid_ids = {e.source_id for e in report.evidence}
    grounded = sum(
        1
        for f in report.key_findings
        if f.evidence_ids and any(eid in valid_ids for eid in f.evidence_ids)
    )
    return grounded / len(report.key_findings)


def section_coverage(report: ResearchReport, target_sections: list[str]) -> float:
    """Fraction of target sections that appear at least once in the evidence."""
    if not target_sections:
        return 1.0
    seen = {e.section for e in report.evidence}
    hit = sum(1 for s in target_sections if s in seen)
    return hit / len(target_sections)


def evidence_diversity(items: list[EvidenceItem]) -> float:
    """Fraction of distinct documents represented in the evidence set."""
    if not items:
        return 0.0
    docs = {e.document_id for e in items}
    return len(docs) / len(items)
