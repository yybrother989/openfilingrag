"""Evidence item — the unit returned by retrieval and cited in reports."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .document import ContentType, DocumentType, SourcePriority


class EvidenceItem(BaseModel):
    """A retrieved snippet plus the metadata needed to cite and rank it.

    ``source_id`` is the chunk's stable identifier (UUID-like string) used
    by the API endpoint ``GET /evidence/{source_id}`` to retrieve the
    original text.
    """

    model_config = ConfigDict(from_attributes=True)

    source_id: str
    document_id: int
    chunk_index: int = 0

    ticker: str
    company_name: str | None = None
    document_type: DocumentType
    fiscal_year: int | None = None
    filing_date: date | None = None
    source_priority: SourcePriority = SourcePriority.PRIMARY_FILING

    section: str
    subsection: str | None = None
    content_type: ContentType = ContentType.PARAGRAPH

    page_start: int | None = None
    page_end: int | None = None

    text: str

    metric_tags: list[str] = Field(default_factory=list)
    risk_tags: list[str] = Field(default_factory=list)

    relevance_score: float = 0.0
    retrieval_reason: str | None = None
    score_breakdown: dict[str, float] | None = None

    extra: dict[str, Any] | None = None
