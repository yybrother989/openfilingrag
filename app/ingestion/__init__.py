"""Document ingestion: parse → split → chunk → enrich → embed → persist.

Parsing/sectioning/chunking/table extraction is delegated to Docling
(see :mod:`.docling_adapter`). This module only re-exports the types
and the orchestration entry point.
"""

from .docling_adapter import DoclingIngestor, IngestionArtifacts
from .metadata_enricher import EnrichedChunk, MetadataEnricher
from .pipeline import IngestionPipeline
from .sec_sections import SECTION_PATTERNS, find_section_breaks, match_canonical_section
from .types import Chunk, DetectedSection, ExtractedTable

__all__ = [
    "SECTION_PATTERNS",
    "Chunk",
    "DetectedSection",
    "DoclingIngestor",
    "EnrichedChunk",
    "ExtractedTable",
    "IngestionArtifacts",
    "IngestionPipeline",
    "MetadataEnricher",
    "find_section_breaks",
    "match_canonical_section",
]
