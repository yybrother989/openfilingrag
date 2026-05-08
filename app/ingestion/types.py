"""Shared dataclasses for the ingestion pipeline.

These describe the intermediate shape produced by the ingestion adapter
and consumed by the DB-write step in :mod:`app.ingestion.pipeline`.
"""

from __future__ import annotations

from dataclasses import dataclass


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


@dataclass
class Chunk:
    section_canonical: str
    raw_heading: str | None
    chunk_text: str
    chunk_index: int
    char_start: int
    char_end: int
    page_start: int | None
    page_end: int | None


@dataclass
class ExtractedTable:
    page: int
    rows: list[list[str]]
    caption: str | None = None
    section_canonical: str | None = None
