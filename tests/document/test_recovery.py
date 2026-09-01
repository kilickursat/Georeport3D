"""Recovering drawing sheets the text layer cannot read, without inventing regions."""

from __future__ import annotations

from document.base import ParsedDocument, ParsedFigure, ParsedPage
from document.docling_adapter import (
    add_page_fallbacks,
    merge_ocr_text,
    sparse_pages,
)
from document.noise import noise_report, strip_noise


def _document(*pages: ParsedPage) -> ParsedDocument:
    return ParsedDocument(source_format="pdf", pages=pages)


def test_sparse_pages_finds_the_drawing_sheets() -> None:
    # Measured on a real report: body pages carried a median of 2,584 characters
    # while the geologic profile sheets carried seven.
    parsed = _document(
        ParsedPage(page_number=1, text="x" * 2584),
        ParsedPage(page_number=2, text="GC4-0031"),
        ParsedPage(page_number=3, text=""),
    )

    assert sparse_pages(parsed) == (2, 3)


def test_sparse_threshold_is_configurable() -> None:
    parsed = _document(ParsedPage(page_number=1, text="x" * 300))

    assert sparse_pages(parsed, threshold=200) == ()
    assert sparse_pages(parsed, threshold=400) == (1,)


def test_merge_takes_ocr_text_only_for_the_named_pages() -> None:
    base = _document(
        ParsedPage(page_number=1, text="body prose that read perfectly well"),
        ParsedPage(page_number=2, text="7 chars"),
    )
    ocr = _document(
        ParsedPage(page_number=1, text="OCR OF A PAGE THAT DID NOT NEED IT"),
        ParsedPage(page_number=2, text="FILL ALLUVIUM LIMESTONE T-201"),
    )

    merged = merge_ocr_text(base, ocr, (2,))

    assert merged.pages[0].text == "body prose that read perfectly well"
    assert merged.pages[1].text == "FILL ALLUVIUM LIMESTONE T-201"


def test_merge_keeps_regions_from_the_base_pass() -> None:
    # OCR changed nothing about region detection on the measured report, so geometry
    # keeps a single source of truth rather than being taken from whichever pass ran
    # last.
    figure = ParsedFigure(page_number=1, kind="figure", bbox=(1.0, 2.0, 3.0, 4.0))
    base = _document(ParsedPage(page_number=1, text="thin", figures=(figure,)))
    ocr = _document(ParsedPage(page_number=1, text="RECOVERED", figures=()))

    merged = merge_ocr_text(base, ocr, (1,))

    assert merged.pages[0].figures == (figure,)


def test_merge_survives_an_ocr_pass_that_skipped_a_page() -> None:
    base = _document(ParsedPage(page_number=1, text="original"))

    merged = merge_ocr_text(base, _document(), (1,))

    assert merged.pages[0].text == "original"


def test_a_drawing_page_with_no_region_gets_the_page_as_its_region() -> None:
    # Nine geologic profile sheets produced no region at all on the real report:
    # nothing to route to a vision model, and no box for a citation to point at.
    parsed = _document(ParsedPage(page_number=7, text="RECOVERED BY OCR"))

    result = add_page_fallbacks(parsed, (7,), {7: (612.0, 792.0)})

    fallback = result.pages[0].figures[0]
    assert fallback.origin == "page_fallback"
    assert fallback.bbox == (0.0, 0.0, 612.0, 792.0)


def test_a_fallback_is_never_added_where_a_region_was_detected() -> None:
    detected = ParsedFigure(page_number=7, kind="figure", bbox=(1.0, 1.0, 2.0, 2.0))
    parsed = _document(ParsedPage(page_number=7, text="thin", figures=(detected,)))

    result = add_page_fallbacks(parsed, (7,), {7: (612.0, 792.0)})

    assert result.pages[0].figures == (detected,)


def test_a_dense_page_never_gets_a_fallback() -> None:
    parsed = _document(ParsedPage(page_number=1, text="x" * 3000))

    result = add_page_fallbacks(parsed, (), {1: (612.0, 792.0)})

    assert result.pages[0].figures == ()


def test_a_fallback_without_a_known_page_size_reports_no_box() -> None:
    # Claiming a box whose extent is unknown would put the "show source" overlay
    # somewhere arbitrary.
    parsed = _document(ParsedPage(page_number=7, text="thin"))

    result = add_page_fallbacks(parsed, (7,), {})

    assert result.pages[0].figures[0].bbox is None
    assert result.pages[0].figures[0].origin == "page_fallback"


def test_noise_strips_machine_generated_title_block_tokens() -> None:
    # Every one of these appeared on every drawing sheet of the measured report.
    recovered = (
        "pw://pwhdruscen01:HDR_US_Central_01/Documents/Dallas_Area_Rapid_Transit "
        "C:\\pwworking\\cen1ro101\\d0894629\\CBD2-GC2-1000.200 "
        "18-FEB-2020 09:56 FILL ALLUVIUM LIMESTONE"
    )

    cleaned = strip_noise(recovered)

    assert "pw://" not in cleaned
    assert "pwworking" not in cleaned
    assert "18-FEB-2020" not in cleaned
    assert cleaned == "FILL ALLUVIUM LIMESTONE"


def test_noise_never_removes_the_payload() -> None:
    # Borehole identifiers, stations, and elevations look structurally similar to
    # the noise. Losing one is far worse than keeping a drawing number.
    payload = "T-201 TS-202 B-3 P-102 R-2 20+00 107+60 417.20 GC4-0031 N=50"

    assert strip_noise(payload) == payload


def test_noise_report_counts_what_would_be_removed() -> None:
    counts = noise_report("18-FEB-2020 09:56 and 17-FEB-2020 18:19")

    assert counts["plot_timestamp"] == 2
    assert counts["uri"] == 0


def test_stripping_empty_text_is_not_an_error() -> None:
    assert strip_noise("") == ""
