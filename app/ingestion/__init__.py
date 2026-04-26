"""Document ingestion: parse → split → chunk → enrich → embed → persist."""

from .chunker import Chunk, Chunker
from .html_parser import HTMLParser, TextParser
from .metadata_enricher import MetadataEnricher
from .pdf_parser import PDFParser
from .pipeline import IngestionPipeline
from .section_splitter import (
    SECTION_PATTERNS,
    DetectedSection,
    SectionSplitter,
)
from .table_extractor import ExtractedTable, TableExtractor

__all__ = [
    "SECTION_PATTERNS",
    "Chunk",
    "Chunker",
    "DetectedSection",
    "ExtractedTable",
    "HTMLParser",
    "IngestionPipeline",
    "MetadataEnricher",
    "PDFParser",
    "SectionSplitter",
    "TableExtractor",
    "TextParser",
]
