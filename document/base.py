"""Contracts for CPU-first document parsing.

The parser boundary is deliberately narrow so that no backend detail, file path, or
document content can reach a caller through an exception. A backend produces plain
structural facts: which pages exist, what text they carry, and where figures and
tables sit. Interpretation belongs to later stages.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

SourceFormat = Literal["pdf", "docx"]
FigureKind = Literal["figure", "table"]


class DocumentParseError(RuntimeError):
    """Generic parse failure that never carries document content or paths."""


class DocumentParserUnavailableError(DocumentParseError):
    """The parser backend is not installed in this environment."""


class UnsupportedDocumentError(DocumentParseError):
    """The file extension is not one of the supported source formats."""


@dataclass(frozen=True)
class ParsedFigure:
    """One figure or table region located on a page."""

    page_number: int
    kind: FigureKind
    bbox: tuple[float, float, float, float] | None = None
    caption: str | None = None

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("page_number must be >= 1")
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

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("page_number must be >= 1")
        for figure in self.figures:
            if figure.page_number != self.page_number:
                raise ValueError("figure page_number must match its page")


@dataclass(frozen=True)
class ParsedDocument:
    """A normalized parse result independent of the backend that produced it.

    `has_source_pagination` is false for flow formats such as DOCX, which carry no
    fixed pages. Content is then collapsed onto a single ordinal page so the evidence
    chain still resolves, but consumers must not present that number as a printed
    page of the source.
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


class DocumentParser(Protocol):
    """Synchronous parsing boundary used by the inventory stage."""

    def parse(self, path: Path) -> ParsedDocument: ...
