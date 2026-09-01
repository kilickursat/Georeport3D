"""CPU-first document inventory for PDF and DOCX geotechnical reports."""

from document.base import (
    DocumentPageLimitError,
    DocumentParseError,
    DocumentParser,
    DocumentParserUnavailableError,
    ParsedDocument,
    ParsedFigure,
    ParsedPage,
    UnsupportedDocumentError,
)
from document.classify import PREPROCESS_VERSION, Classification, classify_figure
from document.inventory import (
    DocumentInventory,
    FigureCandidate,
    PageInventory,
    build_inventory,
)

__all__ = [
    "PREPROCESS_VERSION",
    "Classification",
    "DocumentInventory",
    "DocumentPageLimitError",
    "DocumentParseError",
    "DocumentParser",
    "DocumentParserUnavailableError",
    "FigureCandidate",
    "PageInventory",
    "ParsedDocument",
    "ParsedFigure",
    "ParsedPage",
    "UnsupportedDocumentError",
    "build_inventory",
    "classify_figure",
]
