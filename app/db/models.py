"""SQLAlchemy ORM models matching app/db/migrations/001_init.sql."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    JSON,
    TIMESTAMP,
    Computed,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base for all OpenFilingRAG ORM models."""


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(512))
    sector: Mapped[str | None] = mapped_column(String(128), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(256), nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="company", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    company_name: Mapped[str] = mapped_column(String(512))
    document_type: Mapped[str] = mapped_column(String(64), index=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_priority: Mapped[str] = mapped_column(
        String(64), default="primary_filing", index=True
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    company: Mapped[Company] = relationship("Company", back_populates="documents")
    sections: Mapped[list["DocumentSection"]] = relationship(
        "DocumentSection", back_populates="document", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )
    tables: Mapped[list["FinancialTable"]] = relationship(
        "FinancialTable", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentSection(Base):
    __tablename__ = "document_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    canonical_name: Mapped[str] = mapped_column(String(128), index=True)
    raw_heading: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)

    document: Mapped[Document] = relationship("Document", back_populates="sections")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), unique=True, default=uuid.uuid4
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    section_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_sections.id", ondelete="SET NULL"), nullable=True
    )

    ticker: Mapped[str] = mapped_column(String(16), index=True)
    company_name: Mapped[str] = mapped_column(String(512))
    document_type: Mapped[str] = mapped_column(String(64), index=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_priority: Mapped[str] = mapped_column(
        String(64), default="primary_filing", index=True
    )

    section: Mapped[str] = mapped_column(String(128), index=True)
    subsection: Mapped[str | None] = mapped_column(String(256), nullable=True)
    content_type: Mapped[str] = mapped_column(String(64), default="paragraph", index=True)

    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)

    chunk_text: Mapped[str] = mapped_column(Text)
    metric_tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    risk_tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.pgvector_dim), nullable=True
    )

    # Generated tsvector — populated by Postgres from chunk_text. Declared
    # on the ORM (with Computed so SQLAlchemy knows not to write to it)
    # so KeywordSearch can build queries against DocumentChunk.tsv.
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(chunk_text, ''))", persisted=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    document: Mapped[Document] = relationship("Document", back_populates="chunks")


class FinancialTable(Base):
    __tablename__ = "financial_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    section_canonical: Mapped[str | None] = mapped_column(String(128), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    rows: Mapped[Any] = mapped_column(JSON)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    document: Mapped[Document] = relationship("Document", back_populates="tables")


class ResearchReportRow(Base):
    __tablename__ = "research_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), unique=True, default=uuid.uuid4
    )
    query: Mapped[str] = mapped_column(Text)
    ticker: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    company_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class EvidenceItemRow(Base):
    __tablename__ = "evidence_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("research_reports.report_id", ondelete="CASCADE"), nullable=True
    )
    chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=True
    )
    payload: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
