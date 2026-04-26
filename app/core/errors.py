"""Typed exceptions raised across the OpenFilingRAG stack."""

from __future__ import annotations


class OpenFilingRAGError(Exception):
    """Base class for all application errors."""


class IngestionError(OpenFilingRAGError):
    """Raised when a document cannot be parsed or stored."""


class UnsupportedFormatError(IngestionError):
    """Raised when the file extension is not supported."""


class RetrievalError(OpenFilingRAGError):
    """Raised when retrieval fails or returns no candidates for a required query."""


class LLMError(OpenFilingRAGError):
    """Raised when an LLM call fails or returns malformed output."""


class EmbeddingError(OpenFilingRAGError):
    """Raised when embedding generation fails."""


class ComplianceViolation(OpenFilingRAGError):
    """Raised when output contains restricted financial-advice language."""


class ExternalAPIError(OpenFilingRAGError):
    """Raised when a third-party data source (Alpha Vantage, Massive, ...) fails."""
