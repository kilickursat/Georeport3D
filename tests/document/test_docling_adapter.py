"""Adapter behaviour proven against a structural fake, without importing Docling."""

from __future__ import annotations

from pathlib import Path

import pytest

from document.base import (
    DocumentPageLimitError,
    DocumentParseError,
    DocumentParserUnavailableError,
    UnsupportedDocumentError,
)
from document.docling_adapter import DoclingDocumentParser, to_parsed_document


class _FakeBBox:
    """Emulates the two coordinate origins Docling can report."""

    def __init__(
        self,
        left: float,
        top: float,
        right: float,
        bottom: float,
        origin: str = "TOPLEFT",
    ) -> None:
        self.left, self.top, self.right, self.bottom = left, top, right, bottom
        self.origin = origin
        self.coord_origin = origin

    def to_top_left_origin(self, page_height: float) -> _FakeBBox:
        if self.origin == "TOPLEFT":
            return self
        return _FakeBBox(
            self.left,
            page_height - self.top,
            self.right,
            page_height - self.bottom,
        )

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.left, self.top, self.right, self.bottom)


class _Prov:
    def __init__(self, page_no: object, bbox: object = None) -> None:
        self.page_no = page_no
        self.bbox = bbox


class _Size:
    def __init__(self, height: float) -> None:
        self.height = height


class _Page:
    def __init__(self, height: float) -> None:
        self.size = _Size(height)


class _Text:
    def __init__(self, text: str, page_no: object) -> None:
        self.text = text
        self.prov = [_Prov(page_no)]


class _Region:
    def __init__(self, page_no: object, bbox: object = None, caption: str = "") -> None:
        self.prov = [_Prov(page_no, bbox)]
        self._caption = caption

    def caption_text(self, _document: object) -> str:
        return self._caption


class _FailingCaption(_Region):
    def caption_text(self, _document: object) -> str:
        raise RuntimeError("caption unavailable")


class _Document:
    def __init__(
        self,
        pages: dict | None = None,
        texts: list | None = None,
        pictures: list | None = None,
        tables: list | None = None,
    ) -> None:
        self.pages = pages or {}
        self.texts = texts or []
        self.pictures = pictures or []
        self.tables = tables or []


def test_bottom_left_bbox_is_converted_to_top_left() -> None:
    document = _Document(
        pages={1: _Page(height=800.0)},
        pictures=[_Region(1, _FakeBBox(10.0, 200.0, 50.0, 100.0, origin="BOTTOMLEFT"))],
    )

    parsed = to_parsed_document("pdf", document)

    assert parsed.pages[0].figures[0].bbox == (10.0, 600.0, 50.0, 700.0)


def test_top_left_bbox_is_left_alone() -> None:
    document = _Document(
        pages={1: _Page(height=800.0)},
        pictures=[_Region(1, _FakeBBox(10.0, 20.0, 50.0, 60.0))],
    )

    assert to_parsed_document("pdf", document).pages[0].figures[0].bbox == (
        10.0,
        20.0,
        50.0,
        60.0,
    )


def test_inverted_bbox_is_ordered_rather_than_rejected() -> None:
    document = _Document(
        pages={1: _Page(height=800.0)},
        pictures=[_Region(1, _FakeBBox(50.0, 60.0, 10.0, 20.0))],
    )

    assert to_parsed_document("pdf", document).pages[0].figures[0].bbox == (
        10.0,
        20.0,
        50.0,
        60.0,
    )


def test_unconvertible_bbox_is_dropped_rather_than_reported_flipped() -> None:
    # No page height means a bottom-left box cannot be converted. Reporting no
    # region is honest; reporting a vertically flipped one would be a wrong citation.
    document = _Document(
        pictures=[_Region(1, _FakeBBox(10.0, 200.0, 50.0, 100.0, origin="BOTTOMLEFT"))],
    )

    assert to_parsed_document("pdf", document).pages[0].figures[0].bbox is None


def test_top_left_bbox_survives_a_missing_page_height() -> None:
    document = _Document(pictures=[_Region(1, _FakeBBox(10.0, 20.0, 50.0, 60.0))])

    assert to_parsed_document("pdf", document).pages[0].figures[0].bbox == (
        10.0,
        20.0,
        50.0,
        60.0,
    )


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_bbox_is_dropped(non_finite: float) -> None:
    document = _Document(
        pages={1: _Page(height=800.0)},
        pictures=[_Region(1, _FakeBBox(non_finite, 20.0, non_finite, 60.0))],
    )

    assert to_parsed_document("pdf", document).pages[0].figures[0].bbox is None


def test_page_text_is_joined_in_document_order() -> None:
    document = _Document(
        pages={1: _Page(height=800.0)},
        texts=[_Text("first", 1), _Text("  ", 1), _Text("second", 1)],
    )

    assert to_parsed_document("pdf", document).pages[0].text == "first\nsecond"


def test_tables_and_pictures_are_both_inventoried() -> None:
    document = _Document(
        pages={1: _Page(height=800.0)},
        pictures=[_Region(1, caption="Borehole log")],
        tables=[_Region(1, caption="Summary")],
    )

    kinds = [figure.kind for figure in to_parsed_document("pdf", document).pages[0].figures]
    assert sorted(kinds) == ["figure", "table"]


def test_regions_without_usable_page_numbers_are_preserved_on_a_synthetic_page() -> None:
    document = _Document(
        pages={1: _Page(height=800.0)},
        pictures=[_Region(None), _Region(0), _Region("2")],
    )

    parsed = to_parsed_document("pdf", document)

    assert [page.page_number for page in parsed.pages] == [1, 2]
    assert parsed.pages[0].figures == ()
    assert len(parsed.pages[1].figures) == 3
    assert parsed.pages[1].has_source_pagination is False
    assert parsed.has_source_pagination is False


def test_unreadable_caption_does_not_fail_the_parse() -> None:
    document = _Document(
        pages={1: _Page(height=800.0)},
        pictures=[_FailingCaption(1)],
    )

    assert to_parsed_document("pdf", document).pages[0].figures[0].caption is None


def test_pages_are_emitted_in_order_even_when_sources_disagree() -> None:
    document = _Document(
        pages={3: _Page(height=800.0), 1: _Page(height=800.0)},
        texts=[_Text("on two", 2)],
    )

    numbers = [page.page_number for page in to_parsed_document("pdf", document).pages]
    assert numbers == [1, 2, 3]


def test_empty_document_parses_to_no_pages() -> None:
    assert to_parsed_document("docx", _Document()).pages == ()


def test_unsupported_suffix_is_refused_before_conversion() -> None:
    def _must_not_run() -> object:
        raise AssertionError("converter must not be built for an unsupported format")

    parser = DoclingDocumentParser(converter_factory=_must_not_run)

    with pytest.raises(UnsupportedDocumentError):
        parser.parse(Path("report.txt"))


def test_converter_failure_becomes_a_generic_parse_error() -> None:
    class _Boom:
        def convert(self, source: object) -> object:
            raise RuntimeError("/secret/path/report.pdf is corrupt at page 12")

    parser = DoclingDocumentParser(converter_factory=_Boom)

    with pytest.raises(DocumentParseError) as excinfo:
        parser.parse(Path("/secret/path/report.pdf"))

    assert "secret" not in str(excinfo.value)
    assert str(excinfo.value) == "document could not be parsed"
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_converter_factory_failure_becomes_a_detached_generic_parse_error() -> None:
    def _boom() -> object:
        raise RuntimeError("/secret/path/report.pdf failed during construction")

    with pytest.raises(DocumentParseError) as excinfo:
        DoclingDocumentParser(converter_factory=_boom).parse(Path("/secret/path/report.pdf"))

    assert str(excinfo.value) == "document could not be parsed"
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_normalization_failure_becomes_a_detached_generic_parse_error() -> None:
    class _BrokenDocument:
        @property
        def pages(self) -> object:
            raise RuntimeError("/secret/path/report.pdf failed during normalization")

    class _Result:
        document = _BrokenDocument()

    class _Converter:
        def convert(self, source: object) -> object:
            return _Result()

    with pytest.raises(DocumentParseError) as excinfo:
        DoclingDocumentParser(converter_factory=_Converter).parse(
            Path("/secret/path/report.pdf")
        )

    assert str(excinfo.value) == "document could not be parsed"
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_unavailable_backend_is_reported_distinctly() -> None:
    original = DocumentParserUnavailableError("/secret/path/report.pdf backend missing")

    def _missing() -> object:
        raise original

    parser = DoclingDocumentParser(converter_factory=_missing)

    with pytest.raises(DocumentParserUnavailableError) as excinfo:
        parser.parse(Path("report.pdf"))

    assert excinfo.value is not original
    assert str(excinfo.value) == "document parser is not installed"
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_successful_parse_uses_the_injected_converter() -> None:
    class _Result:
        document = _Document(pages={1: _Page(height=800.0)}, texts=[_Text("hello", 1)])

    class _Converter:
        def convert(self, source: object) -> object:
            return _Result()

    parsed = DoclingDocumentParser(converter_factory=_Converter).parse(Path("r.pdf"))

    assert parsed.source_format == "pdf"
    assert parsed.pages[0].text == "hello"


def test_page_limit_is_enforced_after_normalization() -> None:
    converted: list[Path] = []

    class _Result:
        document = _Document(pages={1: _Page(height=800.0), 2: _Page(height=800.0)})

    class _Converter:
        def convert(self, source: Path) -> object:
            converted.append(source)
            return _Result()

    path = Path("report.pdf")
    with pytest.raises(DocumentPageLimitError, match="page limit") as excinfo:
        DoclingDocumentParser(converter_factory=_Converter, max_pages=1).parse(path)

    assert converted == [path]
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_default_page_limit_is_500_normalized_pages() -> None:
    class _Result:
        document = _Document(
            pages={page: _Page(height=800.0) for page in range(1, 502)}
        )

    class _Converter:
        def convert(self, source: Path) -> object:
            return _Result()

    with pytest.raises(DocumentPageLimitError):
        DoclingDocumentParser(converter_factory=_Converter).parse(Path("report.pdf"))


@pytest.mark.parametrize("invalid", [0, -1, True, 1.5, "2", None])
def test_page_limit_must_be_a_positive_non_boolean_integer(invalid: object) -> None:
    with pytest.raises(ValueError, match="max_pages"):
        DoclingDocumentParser(max_pages=invalid)  # type: ignore[arg-type]


def test_flow_document_without_pages_collapses_to_one_ordinal_page() -> None:
    # DOCX reports no pages and no per-item provenance. Dropping the content would
    # make the whole format unusable; silently claiming "page 1" of the source
    # would be a false citation. The result is one ordinal page, clearly flagged.
    document = _Document(
        texts=[_Text("Borehole log BH-07", None)],
        tables=[_Region(None, caption="Summary")],
    )

    parsed = to_parsed_document("docx", document)

    assert parsed.has_source_pagination is False
    assert len(parsed.pages) == 1
    assert parsed.pages[0].has_source_pagination is False
    assert parsed.pages[0].text == "Borehole log BH-07"
    assert parsed.pages[0].figures[0].kind == "table"


def test_paginated_document_keeps_source_pagination() -> None:
    document = _Document(pages={1: _Page(height=800.0)}, texts=[_Text("hello", 1)])

    parsed = to_parsed_document("pdf", document)

    assert parsed.has_source_pagination is True
    assert parsed.pages[0].has_source_pagination is True


def test_mixed_placed_and_unplaced_content_is_retained_with_page_truth() -> None:
    document = _Document(
        pages={1: _Page(height=800.0)},
        texts=[_Text("placed", 1), _Text("unplaced", None)],
        pictures=[_Region(1, caption="placed"), _Region(None, caption="unplaced figure")],
        tables=[_Region(0, caption="unplaced table")],
    )

    parsed = to_parsed_document("pdf", document)

    assert [page.page_number for page in parsed.pages] == [1, 2]
    assert [page.has_source_pagination for page in parsed.pages] == [True, False]
    assert parsed.pages[1].text == "unplaced"
    assert [figure.caption for figure in parsed.pages[1].figures] == [
        "unplaced figure",
        "unplaced table",
    ]
    assert parsed.has_source_pagination is False


def test_docx_pagination_is_synthetic_even_when_backend_reports_pages() -> None:
    document = _Document(pages={1: _Page(height=800.0)}, texts=[_Text("flow", 1)])

    parsed = to_parsed_document("docx", document)

    assert parsed.pages[0].has_source_pagination is False
    assert parsed.has_source_pagination is False


def test_empty_document_is_not_marked_unpaginated() -> None:
    assert to_parsed_document("docx", _Document()).has_source_pagination is True
