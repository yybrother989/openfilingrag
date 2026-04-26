"""Pydantic schemas for documents, local files, sections, chunks, and tables."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentType(str, Enum):
    ANNUAL_REPORT = "annual_report"
    TEN_K = "10-K"
    TEN_Q = "10-Q"
    EIGHT_K = "8-K"
    EARNINGS_TRANSCRIPT = "earnings_transcript"
    INVESTOR_PRESENTATION = "investor_presentation"
    PRESS_RELEASE = "press_release"
    OTHER = "other"


class SourcePriority(str, Enum):
    PRIMARY_FILING = "primary_filing"
    COMPANY_PRESENTATION = "company_presentation"
    EARNINGS_TRANSCRIPT = "earnings_transcript"
    NEWS = "news"
    OTHER = "other"


class ContentType(str, Enum):
    PARAGRAPH = "paragraph"
    TABLE = "table"
    FOOTNOTE = "footnote"
    HEADER = "header"
    RISK_FACTOR = "risk_factor"
    MDA = "mda"
    FINANCIAL_STATEMENT = "financial_statement"
    BUSINESS_OVERVIEW = "business_overview"
    OUTLOOK = "outlook"
    SEGMENT = "segment"
    OTHER = "other"


class CanonicalSection(str, Enum):
    """Canonical filing section names — keep stable for routing logic."""

    BUSINESS = "Business"
    RISK_FACTORS = "Risk Factors"
    UNRESOLVED_STAFF_COMMENTS = "Unresolved Staff Comments"
    PROPERTIES = "Properties"
    LEGAL_PROCEEDINGS = "Legal Proceedings"
    MINE_SAFETY = "Mine Safety Disclosures"
    MARKET_FOR_REGISTRANT = "Market for Registrant's Common Equity"
    SELECTED_FINANCIAL_DATA = "Selected Financial Data"
    MDA = "Management Discussion and Analysis"
    QUANTITATIVE_QUALITATIVE = "Quantitative and Qualitative Disclosures"
    FINANCIAL_STATEMENTS = "Financial Statements"
    NOTES_TO_FINANCIAL = "Notes to Financial Statements"
    LIQUIDITY = "Liquidity and Capital Resources"
    SEGMENT_INFORMATION = "Segment Information"
    CONTROLS_AND_PROCEDURES = "Controls and Procedures"
    OUTLOOK = "Outlook / Guidance"
    OTHER = "Other"


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ticker: str
    name: str
    sector: str | None = None
    industry: str | None = None


class DocumentMetadata(BaseModel):
    """Metadata supplied at ingestion time for a single document."""

    ticker: str = Field(..., description="Uppercase ticker symbol, e.g. AAPL.")
    company_name: str
    document_type: DocumentType
    fiscal_year: int | None = None
    filing_date: date | None = None
    source_url: str | None = None
    source_priority: SourcePriority = SourcePriority.PRIMARY_FILING


class SectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    document_id: int
    canonical_name: str
    raw_heading: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    char_start: int
    char_end: int


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ticker: str
    company_name: str
    document_type: DocumentType
    fiscal_year: int | None = None
    filing_date: date | None = None
    source_url: str | None = None
    source_priority: SourcePriority
    page_count: int | None = None
    sections_count: int | None = None
    chunks_count: int | None = None
    tables_count: int | None = None
    raw_path: str | None = None
    created_at: datetime | None = None


class LocalFileEntry(BaseModel):
    name: str
    relative_path: str
    local_path: str
    kind: str
    extension: str | None = None
    size_bytes: int | None = None
    modified_at: datetime


class IngestionResult(BaseModel):
    document_id: int
    ticker: str
    company_name: str
    document_type: DocumentType
    sections_count: int
    chunks_count: int
    tables_count: int
    status: str = "ok"
    warnings: list[str] = Field(default_factory=list)


class FinancialTableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    document_id: int
    section_canonical: str | None = None
    page: int | None = None
    caption: str | None = None
    rows: list[list[str]]
    extra: dict[str, Any] | None = None
