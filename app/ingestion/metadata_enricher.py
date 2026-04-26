"""Heuristic content-type classification + metric/risk tag extraction.

This is intentionally rule-based — fast, free, and deterministic. Tags
become first-class filters in the hybrid retriever (e.g. "show me chunks
tagged `revenue` from MD&A").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.document import CanonicalSection, ContentType


@dataclass
class EnrichedChunk:
    content_type: str
    metric_tags: list[str]
    risk_tags: list[str]


# ----------------------------------------------------------------------
# Section → default content_type mapping
# ----------------------------------------------------------------------
SECTION_TO_CONTENT_TYPE: dict[str, ContentType] = {
    CanonicalSection.BUSINESS.value: ContentType.BUSINESS_OVERVIEW,
    CanonicalSection.RISK_FACTORS.value: ContentType.RISK_FACTOR,
    CanonicalSection.MDA.value: ContentType.MDA,
    CanonicalSection.FINANCIAL_STATEMENTS.value: ContentType.FINANCIAL_STATEMENT,
    CanonicalSection.NOTES_TO_FINANCIAL.value: ContentType.FINANCIAL_STATEMENT,
    CanonicalSection.LIQUIDITY.value: ContentType.MDA,
    CanonicalSection.SEGMENT_INFORMATION.value: ContentType.SEGMENT,
    CanonicalSection.OUTLOOK.value: ContentType.OUTLOOK,
    CanonicalSection.LEGAL_PROCEEDINGS.value: ContentType.RISK_FACTOR,
}

# ----------------------------------------------------------------------
# Metric tags — broad financial concept keywords
# ----------------------------------------------------------------------
METRIC_TAG_PATTERNS: dict[str, list[str]] = {
    "revenue":            [r"\brevenue", r"\bnet sales\b", r"\btop[- ]line\b"],
    "gross_margin":       [r"\bgross margin", r"\bgross profit"],
    "operating_margin":   [r"\boperating margin", r"\boperating income"],
    "net_income":         [r"\bnet income", r"\bnet earnings"],
    "eps":                [r"\bearnings per share\b", r"\beps\b", r"\bdiluted (?:eps|earnings)\b"],
    "cash_flow":          [r"\bcash (?:from|flow)", r"\bfree cash flow", r"\boperating cash"],
    "capex":              [r"\bcapital expenditures?\b", r"\bcap ?ex\b"],
    "debt":               [r"\blong[- ]term debt\b", r"\btotal debt\b", r"\bborrowings\b"],
    "liquidity":          [r"\bliquidity\b", r"\bcash and (?:cash )?equivalents"],
    "guidance":           [r"\bguidance\b", r"\boutlook\b", r"\bexpects? to\b", r"\banticipate"],
    "segment":            [r"\bsegment\b", r"\boperating segments?\b"],
    "rd_expense":         [r"\bresearch and development\b", r"\bR&D\b"],
    "sga":                [r"\bselling, general and administrative\b", r"\bSG&A\b"],
    "dividend":           [r"\bdividend"],
    "buyback":            [r"\bshare (?:repurchase|buyback)", r"\btreasury stock"],
}

# ----------------------------------------------------------------------
# Risk tags — taxonomy used by the risk-analysis intent
# ----------------------------------------------------------------------
RISK_TAG_PATTERNS: dict[str, list[str]] = {
    "macroeconomic":      [r"\binflation\b", r"\binterest rate", r"\brecession", r"\bmacroeconomic"],
    "competition":        [r"\bcompetition\b", r"\bcompetitive\b", r"\bcompetitors\b"],
    "regulation":         [r"\bregulation\b", r"\bregulatory\b", r"\bcompliance\b"],
    "litigation":         [r"\blitigation\b", r"\blawsuits?\b", r"\blegal proceedings\b"],
    "supply_chain":       [r"\bsupply chain", r"\bsuppliers?\b", r"\bshortage"],
    "fx":                 [r"\bforeign (?:currency|exchange)\b", r"\bfx\b"],
    "cybersecurity":      [r"\bcyber\b", r"\bdata breach\b", r"\binformation security"],
    "concentration":      [r"\bcustomer concentration\b", r"\bsingle customer\b"],
    "dependency":         [r"\bdepend(?:ence|s|ent) on\b"],
    "ip":                 [r"\bintellectual property\b", r"\bpatents?\b", r"\btrademarks?\b"],
    "geopolitical":       [r"\bgeopolitical\b", r"\bsanctions\b", r"\btariffs\b"],
    "climate":            [r"\bclimate\b", r"\benvironmental\b", r"\bESG\b"],
    "talent":             [r"\bkey personnel\b", r"\btalent\b", r"\battract.*employees"],
}


class MetadataEnricher:
    def __init__(self) -> None:
        self._metric_compiled = {
            tag: [re.compile(p, re.IGNORECASE) for p in pats]
            for tag, pats in METRIC_TAG_PATTERNS.items()
        }
        self._risk_compiled = {
            tag: [re.compile(p, re.IGNORECASE) for p in pats]
            for tag, pats in RISK_TAG_PATTERNS.items()
        }

    def enrich(self, chunk_text: str, section_canonical: str) -> EnrichedChunk:
        content_type = self._classify_content(chunk_text, section_canonical)
        metric_tags = sorted({
            tag
            for tag, pats in self._metric_compiled.items()
            if any(p.search(chunk_text) for p in pats)
        })
        risk_tags = sorted({
            tag
            for tag, pats in self._risk_compiled.items()
            if any(p.search(chunk_text) for p in pats)
        })
        return EnrichedChunk(
            content_type=content_type,
            metric_tags=metric_tags,
            risk_tags=risk_tags,
        )

    def _classify_content(self, text: str, section_canonical: str) -> str:
        # Section default
        section_default = SECTION_TO_CONTENT_TYPE.get(section_canonical)

        # Heuristic overrides for table-like or footnote-like content
        if self._looks_like_table(text):
            return ContentType.TABLE.value
        if self._looks_like_footnote(text):
            return ContentType.FOOTNOTE.value

        if section_default is not None:
            return section_default.value
        return ContentType.PARAGRAPH.value

    @staticmethod
    def _looks_like_table(text: str) -> bool:
        # Many numeric tokens or many pipe/tab separators → table-ish
        digits = sum(1 for ch in text if ch.isdigit())
        if digits > 60 and len(text) < 2000:
            ratio = digits / max(len(text), 1)
            if ratio > 0.08:
                return True
        if text.count("|") > 4 or text.count("\t") > 4:
            return True
        return False

    @staticmethod
    def _looks_like_footnote(text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return False
        if re.match(r"^\(?\d+\)?[\.\s]", stripped) and len(stripped) < 600:
            return True
        return False
