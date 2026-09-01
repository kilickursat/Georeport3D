"""Contracts for CPU-first document parsing.

The parser boundary is deliberately narrow so that no backend detail, file path, or
document content can reach a caller through an exception. A backend produces plain
structural facts: which pages exist, what text they carry, and where figures and
tables sit. Interpretation belongs to later stages.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

SourceFormat = Literal["pdf", "docx"]
FigureKind = Literal["figure", "table"]

# How a region came to exist. `detected` means the layout model located it and its
# bbox marks a real feature. `page_fallback` means no region was detected on a page
# that clearly carries one - a full-page engineering drawing - so the page itself is
# offered as the region. Its bbox is the page, so a citation built from it must not
# be presented as pointing at a located feature.
RegionOrigin = Literal["detected", "page_fallback"]


class DocumentParseError(RuntimeError):
    """Generic parse failure that never carries document content or paths."""


class DocumentParserUnavailableError(DocumentParseError):
    """The parser backend is not installed in this environment."""


class UnsupportedDocumentError(DocumentParseError):
    """The file extension is not one of the supported source formats."""


class DocumentPageLimitError(DocumentParseError):
    """The normalized document contains more pages than the parser permits."""


@dataclass(frozen=True)
class ParsedFigure:
    """One figure or table region located on a page."""

    page_number: int
    kind: FigureKind
    bbox: tuple[float, float, float, float] | None = None
    caption: str | None = None
    origin: RegionOrigin = "detected"

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("page_number must be >= 1")
        if self.bbox is not None and not all(math.isfinite(value) for value in self.bbox):
            raise ValueError("bbox values must be finite")
        if self.bbox is not None and (
            self.bbox[2] < self.bbox[0] or self.bbox[3] < self.bbox[1]
        ):
            raise ValueError("bbox maximums must be >= minimums")


@dataclass(frozen=True)
class ParsedPage:
    """One page and the regions found on it."""

    page_number: int
    text: str = ""
    figures: tuple[ParsedFigure, ...] = ()
    # False when this ordinal was assigned during normalization rather than read
    # from a fixed-page source.
    has_source_pagination: bool = True

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("page_number must be >= 1")
        for figure in self.figures:
            if figure.page_number != self.page_number:
                raise ValueError("figure page_number must match its page")


@dataclass(frozen=True)
class ParsedDocument:
    """A normalized parse result independent of the backend that produced it.

    `has_source_pagination` is false when any content has only a synthetic ordinal,
    including flow formats such as DOCX. Each page carries the same fact at page
    granularity so mixed PDF content does not erase the truth of its real pages.
    Consumers must never present a synthetic ordinal as a printed source page.
    """

    source_format: SourceFormat
    pages: tuple[ParsedPage, ...] = ()
    has_source_pagination: bool = True

    def __post_init__(self) -> None:
        numbers = [page.page_number for page in self.pages]
        if len(set(numbers)) != len(numbers):
            raise ValueError("page numbers must be unique")
        if numbers != sorted(numbers):
            raise ValueError("pages must be ordered by page_number")
        expected_pagination = all(page.has_source_pagination for page in self.pages)
        if self.has_source_pagination != expected_pagination:
            raise ValueError("document pagination must match its pages")
        if self.source_format == "docx" and any(
            page.has_source_pagination for page in self.pages
        ):
            raise ValueError("DOCX page numbers must be synthetic")


class DocumentParser(Protocol):
    """Synchronous parsing boundary used by the inventory stage."""

    def parse(self, path: Path) -> ParsedDocument: ...
