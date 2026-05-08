"""SEC filing canonical-section taxonomy + heading matcher.

The retrieval planner routes by canonical section name (e.g. "Risk
Factors", "Management Discussion and Analysis"). This module owns the
mapping from raw filing headings ("Item 1A. RISK FACTORS", "MD&A", etc.)
to that taxonomy.

Used in two places:
  * :mod:`app.ingestion.docling_adapter` — maps a Docling-extracted
    heading path to a canonical section.
  * Plain-text fallback path — splits raw text on canonical heading
    matches when Docling is not the right parser (.txt/.md inputs).
"""

from __future__ import annotations

import re

from app.schemas.document import CanonicalSection


# Each entry: (canonical name, list of regex patterns).
# Patterns are matched as ANCHORED HEADINGS — case-insensitive, MULTILINE.
SECTION_PATTERNS: list[tuple[CanonicalSection, list[str]]] = [
    (CanonicalSection.BUSINESS, [
        r"^\s*item\s*1\s*[\.\:\-]?\s*business\b",
        r"^\s*item\s*1\b(?!\s*[ab])\.?\s*$",
        r"^\s*business\s+overview\b",
    ]),
    (CanonicalSection.RISK_FACTORS, [
        r"^\s*item\s*1a\s*[\.\:\-]?\s*risk\s*factors\b",
        r"^\s*risk\s*factors\b",
    ]),
    (CanonicalSection.UNRESOLVED_STAFF_COMMENTS, [
        r"^\s*item\s*1b\s*[\.\:\-]?\s*unresolved\s*staff\s*comments\b",
    ]),
    (CanonicalSection.PROPERTIES, [
        r"^\s*item\s*2\s*[\.\:\-]?\s*properties\b",
    ]),
    (CanonicalSection.LEGAL_PROCEEDINGS, [
        r"^\s*item\s*3\s*[\.\:\-]?\s*legal\s*proceedings\b",
        r"^\s*legal\s*proceedings\b",
    ]),
    (CanonicalSection.MINE_SAFETY, [
        r"^\s*item\s*4\s*[\.\:\-]?\s*mine\s*safety\b",
    ]),
    (CanonicalSection.MARKET_FOR_REGISTRANT, [
        r"^\s*item\s*5\s*[\.\:\-]?\s*market\s+for\s+(the\s+)?registrant",
    ]),
    (CanonicalSection.SELECTED_FINANCIAL_DATA, [
        r"^\s*item\s*6\s*[\.\:\-]?\s*(selected\s+financial\s+data|reserved)",
    ]),
    (CanonicalSection.MDA, [
        r"^\s*item\s*7\s*[\.\:\-]?\s*management.{0,10}discussion",
        r"^\s*management.{0,10}discussion\s+and\s+analysis",
        r"^\s*md\s*&\s*a\b",
    ]),
    (CanonicalSection.QUANTITATIVE_QUALITATIVE, [
        r"^\s*item\s*7a\s*[\.\:\-]?\s*quantitative",
        r"^\s*quantitative\s+and\s+qualitative\s+disclosures",
    ]),
    (CanonicalSection.FINANCIAL_STATEMENTS, [
        r"^\s*item\s*8\s*[\.\:\-]?\s*financial\s*statements",
        r"^\s*consolidated\s+(balance\s+sheets|statements\s+of\s+(operations|income|cash\s+flows|equity))",
    ]),
    (CanonicalSection.NOTES_TO_FINANCIAL, [
        r"^\s*notes?\s+to\s+(consolidated\s+)?financial\s+statements",
    ]),
    (CanonicalSection.LIQUIDITY, [
        r"^\s*liquidity\s+and\s+capital\s+resources\b",
    ]),
    (CanonicalSection.SEGMENT_INFORMATION, [
        r"^\s*segment\s+information\b",
        r"^\s*operating\s+segments\b",
    ]),
    (CanonicalSection.CONTROLS_AND_PROCEDURES, [
        r"^\s*item\s*9a\s*[\.\:\-]?\s*controls\s+and\s+procedures",
        r"^\s*controls\s+and\s+procedures\b",
    ]),
    (CanonicalSection.OUTLOOK, [
        r"^\s*outlook\b",
        r"^\s*forward[-\s]looking\s+(statements|guidance)\b",
        r"^\s*guidance\b",
    ]),
]


_COMPILED: list[tuple[CanonicalSection, list[re.Pattern[str]]]] = [
    (canonical, [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in pats])
    for canonical, pats in SECTION_PATTERNS
]


def match_canonical_section(heading: str) -> CanonicalSection | None:
    """Return the canonical section whose pattern matches ``heading``.

    Patterns are anchored (``^``) and case-insensitive. ``heading`` may
    include the original prefix ("Item 1A. ") and is stripped of leading
    whitespace before matching. Returns ``None`` when no pattern matches
    so the caller can decide whether to bucket into ``Other``.
    """
    if not heading:
        return None
    text = heading.lstrip()
    for canonical, patterns in _COMPILED:
        if any(p.match(text) for p in patterns):
            return canonical
    return None


def find_section_breaks(full_text: str) -> list[tuple[int, int, CanonicalSection, str]]:
    """Return (char_start, char_end, canonical, heading_text) for every
    canonical heading found in a raw text block.

    Used by the plain-text fallback path so .txt/.md inputs still get
    section-aware chunks. The result is sorted by char_start with
    same-position duplicates dropped (more specific patterns appear
    first in the registry).
    """
    candidates: list[tuple[int, int, CanonicalSection, str]] = []
    for canonical, patterns in _COMPILED:
        for pat in patterns:
            for m in pat.finditer(full_text):
                candidates.append((m.start(), m.end(), canonical, m.group(0).strip()))
    candidates.sort(key=lambda x: (x[0], x[1]))

    deduped: list[tuple[int, int, CanonicalSection, str]] = []
    seen_starts: set[int] = set()
    for c in candidates:
        if c[0] in seen_starts:
            continue
        seen_starts.add(c[0])
        deduped.append(c)

    if not deduped:
        return deduped

    # TOC awareness: real SEC filings list every heading twice — once in
    # the table of contents (small forward span to next heading) and once
    # at the actual body (large span). Keep the body occurrence.
    by_canonical: dict[CanonicalSection, tuple[int, tuple[int, int, CanonicalSection, str]]] = {}
    for i, c in enumerate(deduped):
        next_start = deduped[i + 1][0] if i + 1 < len(deduped) else len(full_text)
        span = next_start - c[0]
        prev = by_canonical.get(c[2])
        if prev is None or span > prev[0]:
            by_canonical[c[2]] = (span, c)
    kept = {id(v[1]) for v in by_canonical.values()}
    return [c for c in deduped if id(c) in kept]
