"""Ingestion adapter tests.

Covers the plain-text fallback path of :class:`DoclingIngestor` and the
canonical-section heading matcher. The Docling-backed path (PDF/HTML/
DOCX) is exercised in integration tests where the heavyweight layout
models are available.
"""

from __future__ import annotations

from pathlib import Path

from app.ingestion.docling_adapter import DoclingIngestor
from app.ingestion.sec_sections import (
    find_section_breaks,
    match_canonical_section,
)
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


def test_match_canonical_section_recognises_item_headings() -> None:
    assert match_canonical_section("Item 1A. Risk Factors") == CanonicalSection.RISK_FACTORS
    assert match_canonical_section("MD&A") == CanonicalSection.MDA
    assert match_canonical_section("Notes to Consolidated Financial Statements") == (
        CanonicalSection.NOTES_TO_FINANCIAL
    )
    assert match_canonical_section("Random heading nobody cares about") is None


def test_find_section_breaks_returns_canonical_sections_in_order() -> None:
    breaks = find_section_breaks(SAMPLE)
    canonical = [b[2] for b in breaks]
    assert CanonicalSection.BUSINESS in canonical
    assert CanonicalSection.RISK_FACTORS in canonical
    assert CanonicalSection.MDA in canonical
    assert CanonicalSection.LIQUIDITY in canonical
    assert canonical == sorted(canonical, key=lambda c: [b[0] for b in breaks if b[2] == c][0])


def test_plain_text_ingestion_produces_section_aware_chunks(tmp_path: Path) -> None:
    fp = tmp_path / "filing.txt"
    fp.write_text(SAMPLE, encoding="utf-8")
    artifacts = DoclingIngestor().ingest_file(fp)

    canonical_names = {s.canonical_name for s in artifacts.sections}
    assert CanonicalSection.BUSINESS.value in canonical_names
    assert CanonicalSection.RISK_FACTORS.value in canonical_names
    assert CanonicalSection.MDA.value in canonical_names

    assert artifacts.chunks, "expected non-empty chunks for sample text"
    for chunk in artifacts.chunks:
        assert chunk.chunk_text.strip()
        assert chunk.section_canonical in canonical_names
        assert chunk.page_start == 1


def test_plain_text_ingestion_chunks_have_monotonic_indices(tmp_path: Path) -> None:
    fp = tmp_path / "filing.txt"
    fp.write_text(SAMPLE * 4, encoding="utf-8")
    artifacts = DoclingIngestor().ingest_file(fp)
    indices = [c.chunk_index for c in artifacts.chunks]
    assert indices == sorted(indices)
    assert len(set(indices)) == len(indices)


def test_plain_text_force_splits_huge_paragraph(tmp_path: Path) -> None:
    fp = tmp_path / "huge.txt"
    huge = "Item 1. Business\n\n" + ("x" * 20_000)
    fp.write_text(huge, encoding="utf-8")
    artifacts = DoclingIngestor(
        plain_text_target_tokens=200,
        plain_text_max_tokens=400,
    ).ingest_file(fp)
    business_chunks = [c for c in artifacts.chunks if c.section_canonical == CanonicalSection.BUSINESS.value]
    assert len(business_chunks) > 1
