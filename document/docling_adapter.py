"""Docling-backed implementation of the document parser boundary.

Docling is imported lazily so the core package, the API process, and normal CI stay
free of a heavy optional dependency. Conversion from a Docling document to the
normalized contract is a separate pure function, so it can be tested against a
structural fake without installing the backend.

All bounding boxes are normalized to a top-left origin. Docling may report either
origin depending on the backend, and an un-normalized box would place the "show
source" overlay on the wrong part of the page.

## Adaptive OCR

Geotechnical reports arrive in every shape: born-digital prose, scanned paper, and
vector CAD plots exported straight from the drafting system. Measured against a real
105-page baseline report, the text layer alone recovered 3 to 88 characters from the
drawing sheets against a document median of 2,584 - and those sheets carry the
geologic profiles and the borehole location plan, which is to say all of the
subsurface geology. Enabling OCR on them recovered 118 times more text, including
the stratigraphy, the borehole identifiers, and the elevations.

Rather than assume a document is one kind or the other, the parser measures. It
parses once without OCR, finds pages whose text layer is too sparse to be prose, and
re-parses only those with OCR on. A born-digital report pays nothing; a scanned one
is fully recovered. Nothing about the decision depends on the document's language or
house style.

OCR text is a routing signal, not a source of values. It misreads exactly the
characters that matter here - a `15'RT` offset read back as `151RT`, two station
numbers merged into `20+0022+00` - so downstream stages must take values from the
vision model reading the page image, not from this text.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Protocol

from document.base import (
    DocumentParseError,
    DocumentParserUnavailableError,
    ParsedDocument,
    ParsedFigure,
    ParsedPage,
    SourceFormat,
    UnsupportedDocumentError,
)
from document.noise import strip_noise

_SUFFIXES: dict[str, SourceFormat] = {".pdf": "pdf", ".docx": "docx"}

# A page of a technical report carrying fewer characters than this in its text layer
# is not prose. It is a drawing, a scan, or a divider. The threshold is absolute
# rather than relative to the document, because a fully scanned report would have a
# sparse median and a relative rule would then flag nothing at all.
SPARSE_TEXT_CHARS = 200


class _Converter(Protocol):
    def convert(self, source: Any, **kwargs: Any) -> Any: ...


def _source_format(path: Path) -> SourceFormat:
    source_format = _SUFFIXES.get(path.suffix.lower())
    if source_format is None:
        raise UnsupportedDocumentError("unsupported document format")
    return source_format


def _page_heights(document: Any) -> dict[int, float]:
    """Page heights, needed to convert a bottom-left box to a top-left one.

    Kept separate from `_page_sizes` on purpose: a height alone is enough to place a
    box correctly, so requiring a width as well would discard boxes the parser can
    convert perfectly well.
    """
    heights: dict[int, float] = {}
    for page_no, page in (getattr(document, "pages", None) or {}).items():
        height = getattr(getattr(page, "size", None), "height", None)
        if isinstance(height, (int, float)) and height > 0:
            heights[int(page_no)] = float(height)
    return heights


def _page_sizes(document: Any) -> dict[int, tuple[float, float]]:
    """Page width and height, used to size a whole-page fallback region."""
    sizes: dict[int, tuple[float, float]] = {}
    for page_no, page in (getattr(document, "pages", None) or {}).items():
        size = getattr(page, "size", None)
        width, height = getattr(size, "width", None), getattr(size, "height", None)
        if isinstance(width, (int, float)) and isinstance(height, (int, float)):
            if width > 0 and height > 0:
                sizes[int(page_no)] = (float(width), float(height))
    return sizes


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
        left, top, right, bottom = bbox.as_tuple()
    except Exception:  # noqa: BLE001 - same
        return None

    # A rectangle carries the same region regardless of corner order, so ordering the
    # pairs preserves meaning while satisfying the contract's bbox invariant.
    return (
        float(min(left, right)),
        float(min(top, bottom)),
        float(max(left, right)),
        float(max(top, bottom)),
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


def _join(parts: list[str] | tuple[str, ...]) -> str:
    """Join page text and remove machine-generated title-block tokens."""
    return strip_noise("\n".join(parts))


def to_parsed_document(source_format: SourceFormat, document: Any) -> ParsedDocument:
    """Convert one Docling document into the normalized parse contract."""
    texts, unplaced_text = _page_texts(document)
    figures, unplaced_figures = _figures(document, _page_heights(document))

    source_pages = {
        int(page_no)
        for page_no in (getattr(document, "pages", None) or {})
        if int(page_no) >= 1
    }
    page_numbers = sorted(source_pages | set(texts) | set(figures))

    if not page_numbers:
        if not unplaced_text and not unplaced_figures:
            return ParsedDocument(source_format=source_format)
        # A flow format such as DOCX reports no pages at all. Collapse it onto one
        # ordinal page so evidence still resolves to a document and a region, and
        # record that the number is ours rather than the source's.
        return ParsedDocument(
            source_format=source_format,
            pages=(
                ParsedPage(
                    page_number=1,
                    text=_join(unplaced_text),
                    figures=tuple(
                        ParsedFigure(
                            page_number=1,
                            kind=kind,
                            caption=_caption(item, document),
                        )
                        for kind, item in unplaced_figures
                    ),
                ),
            ),
            has_source_pagination=False,
        )

    pages = tuple(
        ParsedPage(
            page_number=page_number,
            text=_join(texts.get(page_number, [])),
            figures=tuple(figures.get(page_number, ())),
        )
        for page_number in page_numbers
    )
    return ParsedDocument(source_format=source_format, pages=pages)


def sparse_pages(parsed: ParsedDocument, threshold: int = SPARSE_TEXT_CHARS) -> tuple[int, ...]:
    """Pages whose text layer is too thin to be prose, and so may need OCR."""
    return tuple(page.page_number for page in parsed.pages if len(page.text) < threshold)


def merge_ocr_text(
    base: ParsedDocument,
    ocr: ParsedDocument,
    pages: tuple[int, ...],
) -> ParsedDocument:
    """Replace the text of `pages` with the OCR pass, keeping detected regions.

    Regions come from the base pass. OCR changes what text a page yields; measured
    against the real report it changed nothing about which regions were detected, so
    taking regions from the base pass keeps one source of truth for geometry.
    """
    replacements = {page.page_number: page.text for page in ocr.pages}
    wanted = set(pages)
    return ParsedDocument(
        source_format=base.source_format,
        pages=tuple(
            ParsedPage(
                page_number=page.page_number,
                text=(
                    replacements.get(page.page_number, page.text)
                    if page.page_number in wanted
                    else page.text
                ),
                figures=page.figures,
            )
            for page in base.pages
        ),
        has_source_pagination=base.has_source_pagination,
    )


def add_page_fallbacks(
    parsed: ParsedDocument,
    pages: tuple[int, ...],
    sizes: dict[int, tuple[float, float]],
) -> ParsedDocument:
    """Offer the page itself as a region where a drawing page yielded none.

    The layout model does not recognise a full-page CAD plot as a figure, so nine
    geologic profile sheets in the measured report produced no region at all: nothing
    to route to the vision model, and no box for a citation to point at. Where a page
    was sparse enough to be a drawing and no region was detected, the page becomes
    the region, marked `page_fallback` so a consumer can tell it apart from a located
    feature.
    """
    wanted = set(pages)
    return ParsedDocument(
        source_format=parsed.source_format,
        pages=tuple(
            ParsedPage(
                page_number=page.page_number,
                text=page.text,
                figures=(
                    page.figures
                    if page.figures or page.page_number not in wanted
                    else (
                        ParsedFigure(
                            page_number=page.page_number,
                            kind="figure",
                            bbox=(
                                (0.0, 0.0, *sizes[page.page_number])
                                if page.page_number in sizes
                                else None
                            ),
                            origin="page_fallback",
                        ),
                    )
                ),
            )
            for page in parsed.pages
        ),
        has_source_pagination=parsed.has_source_pagination,
    )


class DoclingDocumentParser:
    """Parse PDF and DOCX into the normalized inventory contract."""

    def __init__(
        self,
        converter_factory: Any | None = None,
        ocr_converter_factory: Any | None = None,
        *,
        enable_ocr: bool = True,
        sparse_threshold: int = SPARSE_TEXT_CHARS,
    ) -> None:
        # An injected converter substitutes the whole backend. If the caller supplies
        # one and no OCR counterpart, that backend has no OCR mode, and quietly
        # reaching for the real Docling one instead would make a test with a fake
        # converter open real files.
        self._converter_factory = converter_factory or self._default_converter
        if ocr_converter_factory is not None:
            self._ocr_converter_factory = ocr_converter_factory
        elif converter_factory is None:
            self._ocr_converter_factory = self._ocr_converter
        else:
            self._ocr_converter_factory = None
        self._enable_ocr = enable_ocr
        self._sparse_threshold = sparse_threshold

    @staticmethod
    def _pipeline_options(do_ocr: bool) -> Any:
        """Build the lean pipeline the inventory actually needs.

        Table structure recognition runs TableFormer to recover cells inside a
        table. The inventory only needs the table's region and page, which comes
        from layout, so the stage costs time and buys nothing here. It also imports
        opencv, which requires the X11 library `libxcb.so.1` and therefore fails on
        a headless container unless that system package is added to the image.
        """
        try:
            from docling.datamodel.pipeline_options import PdfPipelineOptions
        except ImportError as exc:
            raise DocumentParserUnavailableError("document parser is not installed") from exc

        options = PdfPipelineOptions()
        options.do_ocr = do_ocr
        options.do_table_structure = False
        return options

    @classmethod
    def _build(cls, do_ocr: bool) -> _Converter:
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as exc:
            raise DocumentParserUnavailableError("document parser is not installed") from exc

        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=cls._pipeline_options(do_ocr))
            }
        )

    @classmethod
    def _default_converter(cls) -> _Converter:
        """The fast pass: text layer only, no OCR."""
        return cls._build(do_ocr=False)

    @classmethod
    def _ocr_converter(cls) -> _Converter:
        """The recovery pass, used only on pages the text layer could not read."""
        return cls._build(do_ocr=True)

    @staticmethod
    def _convert(converter: _Converter, path: Path, **kwargs: Any) -> Any:
        try:
            return converter.convert(path, **kwargs).document
        except DocumentParseError:
            raise
        except Exception as exc:
            raise DocumentParseError("document could not be parsed") from exc

    def parse(self, path: Path) -> ParsedDocument:
        """Parse one local document without leaking its content into errors."""
        source_format = _source_format(path)

        document = self._convert(self._converter_factory(), path)
        parsed = to_parsed_document(source_format, document)
        sizes = _page_sizes(document)

        if not parsed.has_source_pagination:
            # A flow format has no pages and no drawing sheets to recover. Its text
            # layer is the document, so sparse text means a short document rather
            # than an unreadable one, and inventing a whole-page region would route
            # a phantom to the vision model.
            return parsed

        sparse = sparse_pages(parsed, self._sparse_threshold)
        if sparse and self._enable_ocr and self._ocr_converter_factory is not None:
            parsed = self._recover(source_format, path, parsed, sparse)

        return add_page_fallbacks(parsed, sparse, sizes)

    def _recover(
        self,
        source_format: SourceFormat,
        path: Path,
        parsed: ParsedDocument,
        sparse: tuple[int, ...],
    ) -> ParsedDocument:
        """Re-read the sparse pages with OCR and merge their text back in.

        A single span covering the sparse pages costs one extra conversion. Reading a
        few dense pages again inside that span is cheaper than orchestrating one
        conversion per run of pages, and produces the same result because only sparse
        pages are merged back.
        """
        try:
            ocr_document = self._convert(
                self._ocr_converter_factory(),
                path,
                page_range=(min(sparse), max(sparse)),
            )
        except DocumentParserUnavailableError:
            # OCR is a recovery path. If the backend cannot provide it, the text
            # layer result still stands and must not be lost.
            return parsed
        return merge_ocr_text(parsed, to_parsed_document(source_format, ocr_document), sparse)
