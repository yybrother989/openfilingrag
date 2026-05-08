"""Numbered-citation indirection for grounded generation.

LlamaIndex ``CitationQueryEngine``-style: each retrieved
:class:`EvidenceItem` is split into ~512-char "citation chunks", each
chunk is given a ``[N]`` tag, and the LLM is told to cite only by
those numbers. The Python side then translates the numbers back to
project-stable ``source_id`` strings.

Two reasons for the indirection:

  1. **Reliability** — LLMs hallucinate UUIDs but rarely hallucinate
     small integers; numbered citations have higher correctness rates.
  2. **Granularity** — citing per-paragraph instead of per-chunk lets
     the UI underline the exact span the claim depends on.

The shape of ``num_to_source_id`` is one-based and dense (1, 2, 3, …).
Numbers the LLM emits that aren't in the map are silently dropped —
the validate node catches the resulting ``len(evidence_ids) == 0`` case
and triggers self-correction.
"""

from __future__ import annotations

import re

from app.schemas.evidence import EvidenceItem


# Target size of one citation chunk. 512 char is roughly 100 tokens —
# small enough that one chunk maps to a single claim, large enough that
# we don't explode the prompt token count.
CITATION_CHUNK_CHARS = 512

# Sentence boundary heuristic. Doesn't need to be perfect — the chunker
# falls back to a hard char split if no boundary is found.
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


def build_citation_corpus(items: list[EvidenceItem]) -> tuple[str, dict[int, str]]:
    """Return (prompt_text, num_to_source_id).

    Splits each ``EvidenceItem.text`` into <=:data:`CITATION_CHUNK_CHARS`
    pieces on sentence boundaries when possible, then numbers them
    globally starting at 1. Each piece is annotated with section + page
    so the LLM can also cite location implicitly in its reasoning.
    """
    if not items:
        return "(no evidence retrieved)", {}

    parts: list[str] = []
    num_map: dict[int, str] = {}
    n = 1
    for item in items:
        for piece in _split_on_sentences(item.text or "", CITATION_CHUNK_CHARS):
            num_map[n] = item.source_id
            header = (
                f"[{n}] (section={item.section}, "
                f"page={item.page_start}-{item.page_end})"
            )
            parts.append(f"{header}\n{piece.strip()}")
            n += 1

    return "\n\n".join(parts), num_map


def numbers_to_source_ids(
    numbers: list[int],
    num_map: dict[int, str],
) -> list[str]:
    """Translate LLM-emitted ``[N]`` numbers to project ``source_id`` strings.

    - Unknown numbers (LLM hallucination) are dropped — the validate
      node will detect the empty list and trigger self-correction.
    - Duplicate source_ids are collapsed while preserving first-seen
      order so the UI shows each citation once.
    """
    seen: set[str] = set()
    out: list[str] = []
    for n in numbers or []:
        sid = num_map.get(n)
        if sid and sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _split_on_sentences(text: str, max_chars: int) -> list[str]:
    """Yield sentence-aligned pieces, each <= ``max_chars`` long.

    Best-effort: if a sentence is itself longer than ``max_chars`` we
    fall back to a hard char split so the LLM still sees the content.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentences = _SENTENCE_BOUNDARY_RE.split(text)
    out: list[str] = []
    buf = ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(s) > max_chars:
            # Sentence too long — flush whatever we have, then hard-split.
            if buf:
                out.append(buf)
                buf = ""
            for i in range(0, len(s), max_chars):
                out.append(s[i : i + max_chars])
            continue
        if buf and len(buf) + 1 + len(s) > max_chars:
            out.append(buf)
            buf = s
        else:
            buf = f"{buf} {s}".strip() if buf else s
    if buf:
        out.append(buf)
    return out
