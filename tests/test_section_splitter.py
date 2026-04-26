"""Section splitter must detect canonical filing headings."""

from __future__ import annotations

from app.ingestion.section_splitter import SectionSplitter
from app.schemas.document import CanonicalSection

SAMPLE = """
Some preamble text describing the cover page.

Item 1. Business

ACME makes widgets and operates in three segments.

Item 1A. Risk Factors

We face many risks: macroeconomic, supply chain, cybersecurity, and
litigation. Each is material.

Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations

Net sales increased and gross margin contracted.

Liquidity and Capital Resources

We ended the year with $612 million of cash.

Item 8. Financial Statements

Consolidated Balance Sheets follow.

Notes to Financial Statements

Note 1. Significant accounting policies.

Segment Information

Aerospace: $1,180M; Industrial: $760M; Energy: $460M.

Item 9A. Controls and Procedures

The CEO and CFO concluded controls were effective.
"""


def test_detects_core_sections() -> None:
    sections = SectionSplitter().split(SAMPLE)
    canonical = [s.canonical_name for s in sections]
    assert CanonicalSection.BUSINESS.value in canonical
    assert CanonicalSection.RISK_FACTORS.value in canonical
    assert CanonicalSection.MDA.value in canonical
    assert CanonicalSection.LIQUIDITY.value in canonical
    assert CanonicalSection.FINANCIAL_STATEMENTS.value in canonical
    assert CanonicalSection.NOTES_TO_FINANCIAL.value in canonical
    assert CanonicalSection.SEGMENT_INFORMATION.value in canonical
    assert CanonicalSection.CONTROLS_AND_PROCEDURES.value in canonical


def test_sections_in_document_order() -> None:
    sections = SectionSplitter().split(SAMPLE)
    starts = [s.char_start for s in sections]
    assert starts == sorted(starts)


def test_each_section_has_meaningful_text() -> None:
    sections = SectionSplitter().split(SAMPLE)
    for sec in sections:
        if sec.canonical_name != CanonicalSection.OTHER.value:
            assert len(sec.text.strip()) > 10
