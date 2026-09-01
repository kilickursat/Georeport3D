"""Docling-backed implementation of the document parser boundary.

Docling is imported lazily so the core package, the API process, and normal CI stay
free of a heavy optional dependency. Conversion from a Docling document to the
normalized contract is a separate pure function, so it can be tested against a
structural fake without installing the backend.

All bounding boxes are normalized to a top-left origin. Docling may report either
origin depending on the backend, and an un-normalized box would place the "show
source" overlay on the wrong part of the page.
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Protocol

from document.base import (
    DocumentPageLimitError,
    DocumentParseError,
    DocumentParserUnavailableError,
    ParsedDocument,
    ParsedFigure,
    ParsedPage,
    SourceFormat,
    UnsupportedDocumentError,
)

_SUFFIXES: dict[str, SourceFormat] = {".pdf": "pdf", ".docx": "docx"}
_DEFAULT_MAX_PAGES = 500


class _Converter(Protocol):
    def convert(self, source: Any) -> Any: ...


def _source_format(path: Path) -> SourceFormat:
    source_format = _SUFFIXES.get(path.suffix.lower())
    if source_format is None:
        raise UnsupportedDocumentError("unsupported document format")
    return source_format


def _page_heights(document: Any) -> dict[int, float]:
    heights: dict[int, float] = {}
    for page_no, page in (getattr(document, "pages", None) or {}).items():
        size = getattr(page, "size", None)
        height = getattr(size, "height", None)
        if isinstance(height, (int, float)) and math.isfinite(height) and height > 0:
            heights[int(page_no)] = float(height)
    return heights


def _first_provenance(item: Any) -> Any | None:
    provenance = getattr(item, "prov", None) or ()
    return provenance[0] if provenance else None


def _bbox(provenance: Any, page_height: float | None) -> tuple[float, float, float, float] | None:
    bbox = getattr(provenance, "bbox", None)
    if bbox is None:
        return None

    origin = getattr(bbox, "coord_origin", None)
    origin_name = getattr(origin, "value", origin)

    if page_height is not None:
        try:
            bbox = bbox.to_top_left_origin(page_height)
        except Exception:  # noqa: BLE001 - a malformed box must not fail the parse
            return None
    elif origin_name != "TOPLEFT":
        # Without the page height a bottom-left box cannot be converted, and a
        # flipped box would point the "show source" overlay at the wrong region.
        # Reporting no region is honest; reporting the wrong one is not.
        return None

    try:
        left, top, right, bottom = (float(value) for value in bbox.as_tuple())
    except Exception:  # noqa: BLE001 - same
        return None

    if not all(math.isfinite(value) for value in (left, top, right, bottom)):
        return None

    # A rectangle carries the same region regardless of corner order, so ordering the
    # pairs preserves meaning while satisfying the contract's bbox invariant.
    return (
        min(left, right),
        min(top, bottom),
        max(left, right),
        max(top, bottom),
    )


def _caption(item: Any, document: Any) -> str | None:
    try:
        caption = item.caption_text(document)
    except Exception:  # noqa: BLE001 - a caption is optional context, never required
        return None
    caption = (caption or "").strip()
    return caption or None


def _page_texts(document: Any) -> tuple[dict[int, list[str]], list[str]]:
    """Group text by page, keeping text that carries no page provenance."""
    texts: dict[int, list[str]] = defaultdict(list)
    unplaced: list[str] = []
    for item in getattr(document, "texts", None) or ():
        text = getattr(item, "text", None)
        if not isinstance(text, str) or not text.strip():
            continue
        page_no = getattr(_first_provenance(item), "page_no", None)
        if isinstance(page_no, int) and page_no >= 1:
            texts[page_no].append(text.strip())
        else:
            unplaced.append(text.strip())
    return texts, unplaced


def _regions(document: Any) -> tuple[tuple[str, Any, Any], ...]:
    return tuple(
        (kind, item, _first_provenance(item))
        for kind, items in (
            ("figure", getattr(document, "pictures", None) or ()),
            ("table", getattr(document, "tables", None) or ()),
        )
        for item in items
    )


def _figures(
    document: Any,
    heights: dict[int, float],
) -> tuple[dict[int, list[ParsedFigure]], list[tuple[str, Any]]]:
    """Group regions by page, keeping regions that carry no page provenance."""
    figures: dict[int, list[ParsedFigure]] = defaultdict(list)
    unplaced: list[tuple[str, Any]] = []
    for kind, item, provenance in _regions(document):
        page_no = getattr(provenance, "page_no", None)
        if not isinstance(page_no, int) or page_no < 1:
            unplaced.append((kind, item))
            continue
        figures[page_no].append(
            ParsedFigure(
                page_number=page_no,
                kind=kind,
                bbox=_bbox(provenance, heights.get(page_no)),
                caption=_caption(item, document),
            )
        )
    return figures, unplaced


def to_parsed_document(source_format: SourceFormat, document: Any) -> ParsedDocument:
    """Convert one Docling document into the normalized parse contract."""
    heights = _page_heights(document)
    texts, unplaced_text = _page_texts(document)
    figures, unplaced_figures = _figures(document, heights)

    source_pages = {
        int(page_no)
        for page_no in (getattr(document, "pages", None) or {})
        if int(page_no) >= 1
    }
    page_numbers = sorted(source_pages | set(texts) | set(figures))

    pages = [
        ParsedPage(
            page_number=page_number,
            text="\n".join(texts.get(page_number, ())),
            figures=tuple(figures.get(page_number, ())),
            has_source_pagination=source_format == "pdf",
        )
        for page_number in page_numbers
    ]

    if unplaced_text or unplaced_figures:
        synthetic_page_number = (page_numbers[-1] if page_numbers else 0) + 1
        pages.append(
            ParsedPage(
                page_number=synthetic_page_number,
                text="\n".join(unplaced_text),
                figures=tuple(
                    ParsedFigure(
                        page_number=synthetic_page_number,
                        kind=kind,
                        caption=_caption(item, document),
                    )
                    for kind, item in unplaced_figures
                ),
                has_source_pagination=False,
            )
        )

    has_source_pagination = all(page.has_source_pagination for page in pages)
    return ParsedDocument(
        source_format=source_format,
        pages=tuple(pages),
        has_source_pagination=has_source_pagination,
    )


class DoclingDocumentParser:
    """Parse PDF and DOCX into the normalized inventory contract."""

    def __init__(
        self,
        converter_factory: Any | None = None,
        *,
        max_pages: int = _DEFAULT_MAX_PAGES,
    ) -> None:
        if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages < 1:
            raise ValueError("max_pages must be a positive integer")
        self._converter_factory = converter_factory or self._default_converter
        self._max_pages = max_pages

    @staticmethod
    def _default_converter() -> _Converter:
        """Build the lean pipeline the inventory actually needs.

        Two of Docling's defaults are switched off deliberately.

        Table structure recognition runs TableFormer to recover cells inside a
        table. The inventory only needs the table's region and page, which comes
        from layout, so the stage costs time and buys nothing here. It also imports
        opencv, which requires the X11 library `libxcb.so.1` and therefore fails on
        a headless container unless that system package is added to the image.

        OCR is off because the inventory reads the text layer. Scanned pages need a
        deliberate decision about an OCR engine, its cost, and its accuracy, rather
        than being switched on by a library default.
        """
        unavailable = False
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError:
            unavailable = True

        if unavailable:
            raise DocumentParserUnavailableError("document parser is not installed") from None

        options = PdfPipelineOptions()
        options.do_ocr = False
        options.do_table_structure = False
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )

    def parse(self, path: Path) -> ParsedDocument:
        """Parse one local document without leaking its content into errors.

        ``max_pages`` is enforced on the normalized result. It prevents an
        over-limit document from entering inventory or inference, but it does not
        bound Docling's conversion work because this adapter cannot rely on a
        stable pre-conversion page-limit API across the supported backend range.
        """
        source_format = _source_format(path)
        parsed: ParsedDocument | None = None
        outward_error: DocumentParseError | None = None
        try:
            converter = self._converter_factory()
            document = converter.convert(path).document
            parsed = to_parsed_document(source_format, document)
        except DocumentParserUnavailableError:
            outward_error = DocumentParserUnavailableError("document parser is not installed")
        except Exception:  # noqa: BLE001 - all backend details stop at this boundary
            outward_error = DocumentParseError("document could not be parsed")

        # Raise only after leaving the handler. This deliberately prevents the
        # backend exception from remaining reachable through __context__ even when
        # callers inspect the outward exception object directly.
        if outward_error is not None:
            raise outward_error from None
        if parsed is None:  # pragma: no cover - every non-success branch sets an error
            raise DocumentParseError("document could not be parsed")
        if len(parsed.pages) > self._max_pages:
            raise DocumentPageLimitError("document exceeds page limit")
        return parsed
