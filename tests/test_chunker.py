"""Chunker must preserve section + page metadata and respect size targets."""

from __future__ import annotations

from app.ingestion.chunker import Chunker
from app.ingestion.section_splitter import DetectedSection
from app.schemas.document import CanonicalSection


def _make_section(text: str, name: str = CanonicalSection.MDA.value) -> DetectedSection:
    return DetectedSection(
        canonical_name=name,
        raw_heading="Item 7. MD&A",
        char_start=0,
        char_end=len(text),
        text=text,
        page_start=10,
        page_end=14,
        ordinal=0,
    )


def test_chunks_inherit_section_and_page() -> None:
    text = "\n\n".join([f"Paragraph number {i}. " + ("filler " * 50) for i in range(40)])
    section = _make_section(text)
    chunker = Chunker(target_tokens=200, overlap_tokens=20, max_tokens=400)

    chunks = chunker.chunk_sections([section])
    assert chunks, "expected non-empty chunks"
    for c in chunks:
        assert c.section_canonical == CanonicalSection.MDA.value
        assert c.raw_heading == "Item 7. MD&A"
        # Page span must be within the original section's range
        assert c.page_start in (None, 10, 11, 12, 13, 14)


def test_chunk_indices_are_monotonic() -> None:
    text = "\n\n".join("para " * 30 for _ in range(20))
    chunks = Chunker(target_tokens=150).chunk_sections([_make_section(text)])
    indices = [c.chunk_index for c in chunks]
    assert indices == sorted(indices)
    assert len(set(indices)) == len(indices)


def test_huge_paragraph_is_force_split() -> None:
    huge = "x" * 20_000
    chunks = Chunker(target_tokens=200, max_tokens=400).chunk_sections([_make_section(huge)])
    assert len(chunks) > 1
