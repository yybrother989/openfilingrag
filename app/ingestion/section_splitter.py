"""Heuristic filing section splitter.

Maps raw heading variants (Item 1, ITEM 1A. RISK FACTORS, etc.) onto the
canonical sections used downstream by the retrieval planner. Keep the
:data:`SECTION_PATTERNS` registry as the single source of truth — nodes
in the graph reference these canonical names by string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas.document import CanonicalSection


@dataclass
class DetectedSection:
    canonical_name: str
    raw_heading: str
    char_start: int
    char_end: int
    page_start: int | None = None
    page_end: int | None = None
    text: str = ""
    ordinal: int = 0


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


@dataclass
class SectionSplitter:
    """Detects canonical filing sections in a parsed document.

    Strategy: find every line that matches a known heading pattern, then
    bucket the text between consecutive headings into the section started
    by the earlier heading. Lines before the first heading are placed in
    a synthetic ``Other`` section.
    """

    # Sections shorter than this are dropped. Kept low so headings with
    # brief lead-in text (a one-sentence ToC pointer to a referenced
    # statement, for example) still get captured.
    min_section_chars: int = 20

    def split(
        self,
        full_text: str,
        char_to_page: list[int] | None = None,
    ) -> list[DetectedSection]:
        compiled: list[tuple[CanonicalSection, re.Pattern[str]]] = []
        for canonical, patterns in SECTION_PATTERNS:
            for p in patterns:
                compiled.append((canonical, re.compile(p, re.IGNORECASE | re.MULTILINE)))

        # Find all candidate heading positions
        candidates: list[tuple[int, int, CanonicalSection, str]] = []
        for canonical, pat in compiled:
            for m in pat.finditer(full_text):
                start = m.start()
                end = m.end()
                heading = m.group(0).strip()
                candidates.append((start, end, canonical, heading))

        # Sort by start position; deduplicate same-position matches keeping
        # the first canonical (patterns are ordered by specificity).
        candidates.sort(key=lambda x: (x[0], x[1]))
        deduped: list[tuple[int, int, CanonicalSection, str]] = []
        seen_starts: set[int] = set()
        for c in candidates:
            if c[0] in seen_starts:
                continue
            seen_starts.add(c[0])
            deduped.append(c)

        # TOC awareness: real SEC HTML filings list every heading twice —
        # once in the table of contents (tiny gap to next heading) and
        # once at the actual section body (large gap). For each canonical
        # section we keep the occurrence with the largest forward span,
        # which is reliably the body. This is a no-op when each heading
        # appears only once (the synthetic / plain-text case).
        if deduped:
            by_canonical: dict[CanonicalSection, tuple[int, tuple[int, int, CanonicalSection, str]]] = {}
            for i, c in enumerate(deduped):
                next_start = deduped[i + 1][0] if i + 1 < len(deduped) else len(full_text)
                span = next_start - c[0]
                prev = by_canonical.get(c[2])
                if prev is None or span > prev[0]:
                    by_canonical[c[2]] = (span, c)
            kept = {id(v[1]) for v in by_canonical.values()}
            deduped = [c for c in deduped if id(c) in kept]

        sections: list[DetectedSection] = []
        if not deduped:
            sections.append(
                DetectedSection(
                    canonical_name=CanonicalSection.OTHER.value,
                    raw_heading="",
                    char_start=0,
                    char_end=len(full_text),
                    text=full_text,
                    page_start=_page_at(char_to_page, 0),
                    page_end=_page_at(char_to_page, max(len(full_text) - 1, 0)),
                    ordinal=0,
                )
            )
            return sections

        # Prefix (text before first heading) → Other
        first_start = deduped[0][0]
        if first_start > self.min_section_chars:
            sections.append(
                DetectedSection(
                    canonical_name=CanonicalSection.OTHER.value,
                    raw_heading="",
                    char_start=0,
                    char_end=first_start,
                    text=full_text[:first_start],
                    page_start=_page_at(char_to_page, 0),
                    page_end=_page_at(char_to_page, max(first_start - 1, 0)),
                    ordinal=0,
                )
            )

        for i, (start, _heading_end, canonical, heading) in enumerate(deduped):
            next_start = deduped[i + 1][0] if i + 1 < len(deduped) else len(full_text)
            text = full_text[start:next_start]
            if len(text) < self.min_section_chars:
                continue
            sections.append(
                DetectedSection(
                    canonical_name=canonical.value,
                    raw_heading=heading,
                    char_start=start,
                    char_end=next_start,
                    text=text,
                    page_start=_page_at(char_to_page, start),
                    page_end=_page_at(char_to_page, max(next_start - 1, 0)),
                    ordinal=len(sections),
                )
            )

        # Renumber ordinal in document order
        for i, sec in enumerate(sections):
            sec.ordinal = i

        return sections


def _page_at(char_to_page: list[int] | None, idx: int) -> int | None:
    if not char_to_page:
        return None
    if idx < 0 or idx >= len(char_to_page):
        return None
    return char_to_page[idx]
