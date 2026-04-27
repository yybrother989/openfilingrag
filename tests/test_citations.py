"""Citation-corpus / number-to-source_id translation correctness."""

from __future__ import annotations

from app.graph.citations import (
    CITATION_CHUNK_CHARS,
    build_citation_corpus,
    numbers_to_source_ids,
)
from app.schemas.document import DocumentType, SourcePriority
from app.schemas.evidence import EvidenceItem


def _ev(text: str, sid: str = "x") -> EvidenceItem:
    return EvidenceItem(
        source_id=sid,
        document_id=1,
        ticker="ACME",
        document_type=DocumentType.TEN_K,
        source_priority=SourcePriority.PRIMARY_FILING,
        section="Risk Factors",
        text=text,
    )


def test_one_chunk_per_short_evidence() -> None:
    items = [_ev("Short text.", "sid-A"), _ev("Another one.", "sid-B")]
    text, num_map = build_citation_corpus(items)
    assert num_map == {1: "sid-A", 2: "sid-B"}
    assert "[1]" in text and "[2]" in text


def test_long_evidence_splits_into_multiple_numbered_chunks() -> None:
    """An EvidenceItem longer than CITATION_CHUNK_CHARS gets split — every
    piece keeps the same source_id but gets its own number."""
    long_text = "x" * (CITATION_CHUNK_CHARS * 3)
    items = [_ev(long_text, "sid-A")]
    _, num_map = build_citation_corpus(items)
    assert len(num_map) == 3
    assert all(sid == "sid-A" for sid in num_map.values())


def test_empty_evidence_returns_placeholder() -> None:
    text, num_map = build_citation_corpus([])
    assert num_map == {}
    assert "no evidence" in text.lower()


def test_numbers_to_source_ids_drops_unknown() -> None:
    num_map = {1: "sid-A", 2: "sid-B"}
    assert numbers_to_source_ids([1, 2, 99], num_map) == ["sid-A", "sid-B"]


def test_numbers_to_source_ids_dedupes_preserving_order() -> None:
    """Numbers that map to the same source_id collapse to one entry,
    keeping the first-seen order so the UI shows each citation once."""
    num_map = {1: "sid-A", 2: "sid-A", 3: "sid-B"}
    assert numbers_to_source_ids([2, 3, 1], num_map) == ["sid-A", "sid-B"]


def test_numbers_to_source_ids_handles_empty_input() -> None:
    assert numbers_to_source_ids([], {1: "sid-A"}) == []
    assert numbers_to_source_ids([1], {}) == []
