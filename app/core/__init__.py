"""Core: configuration, logging, errors."""

from .config import Settings, get_settings, settings
from .errors import (
    ComplianceViolation,
    EmbeddingError,
    ExternalAPIError,
    IngestionError,
    LLMError,
    OpenFilingRAGError,
    RetrievalError,
    UnsupportedFormatError,
)
from .logging import configure_logging, get_logger

__all__ = [
    "ComplianceViolation",
    "EmbeddingError",
    "ExternalAPIError",
    "IngestionError",
    "LLMError",
    "OpenFilingRAGError",
    "RetrievalError",
    "Settings",
    "UnsupportedFormatError",
    "configure_logging",
    "get_logger",
    "get_settings",
    "settings",
]
