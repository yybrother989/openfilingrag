"""Deterministic chunk identifiers.

A chunk's ``source_id`` is what reports cite (``[source_id]``) and what
``GET /evidence/{source_id}`` looks up. We derive it via UUID5 from the
filing's stable identity plus the chunk's content hash, so re-ingesting
the same filing produces the same IDs and prior reports keep resolving.

Identity inputs (in order, joined by ``|``):
  * ``ticker`` (uppercased)
  * ``document_type`` (canonical enum value)
  * ``fiscal_year`` (or empty string when unknown)
  * ``filing_date`` ISO string (or empty)
  * ``source_url`` if present, else ``raw_path`` filename — whichever
    survives across re-ingest is what we want.
  * ``chunk_index`` within the document
  * ``sha256(chunk_text)[:16]`` — guards against text drift while keeping
    the key short.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date

# Project-level namespace for chunk identifiers. Do NOT change this — it
# would invalidate every previously generated source_id in the wild.
CHUNK_NAMESPACE = uuid.UUID("c2f4f9b9-5a4d-4d1e-8b9b-2f4d1e8b9b2f")


def chunk_source_id(
    *,
    ticker: str,
    document_type: str,
    fiscal_year: int | None,
    filing_date: date | None,
    source_url: str | None,
    raw_path: str | None,
    chunk_index: int,
    chunk_text: str,
) -> uuid.UUID:
    """Return a deterministic UUID5 for this chunk."""
    identity = source_url or _filename(raw_path)
    text_digest = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()[:16]
    key = "|".join(
        [
            (ticker or "").upper(),
            document_type or "",
            str(fiscal_year) if fiscal_year is not None else "",
            filing_date.isoformat() if filing_date else "",
            identity or "",
            str(chunk_index),
            text_digest,
        ]
    )
    return uuid.uuid5(CHUNK_NAMESPACE, key)


def _filename(raw_path: str | None) -> str:
    if not raw_path:
        return ""
    # Take the trailing path segment only — absolute paths differ between
    # dev and prod boxes but the filename usually doesn't.
    return raw_path.rsplit("/", 1)[-1]
