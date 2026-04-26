"""Structured logging setup using structlog with stdlib fallback.

Call :func:`configure_logging` once during process startup. After that,
use ``get_logger(__name__)`` everywhere else.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from .config import settings

_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = getattr(logging, settings.log_level, logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )

    # Silence httpx's INFO-level "HTTP Request: GET <full url>" lines.
    # Those URLs include API keys when providers (Alpha Vantage, Massive)
    # authenticate via query string — we never want them in stdout/logs.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str | None = None) -> Any:
    if not _CONFIGURED:
        configure_logging()
    return structlog.get_logger(name or "openfilingrag")
