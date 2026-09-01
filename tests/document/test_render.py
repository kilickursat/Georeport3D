"""Rendering feeds both the model and the cache key, so determinism is correctness."""

from __future__ import annotations

from pathlib import Path

import pytest

from document.render import (
    DEFAULT_DPI,
    RENDER_VERSION,
    RenderError,
    digest_for,
    render_region,
)

pytestmark = pytest.mark.docling  # shares the optional document extra


@pytest.fixture(scope="module")
def pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A two-page PDF with visible content, built rather than committed."""
    pdfium = pytest.importorskip("pypdfium2")
    target = tmp_path_factory.mktemp("render") / "sample.pdf"

    document = pdfium.PdfDocument.new()
    # Different sizes, so the two pages are genuinely distinguishable. Two blank
    # pages of equal size render to identical pixels, and sharing a digest would
    # then be correct rather than a defect.
    for width, height in ((400, 300), (500, 350)):
        page = document.new_page(width, height)
        del page
    document.save(target)
    document.close()
    return target


def test_a_page_renders_to_a_png(pdf: Path) -> None:
    rendered = render_region(pdf, 1)

    assert rendered.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert rendered.page_number == 1
    assert rendered.is_whole_page is True
    assert rendered.width > 0 and rendered.height > 0


def test_rendering_is_byte_identical_across_calls(pdf: Path) -> None:
    """The digest becomes `figure_sha256` in the cache key.

    A renderer that varied between runs would miss every cache hit and pay for the
    same extraction again each time, with nothing failing to reveal it.
    """
    first = render_region(pdf, 1)
    second = render_region(pdf, 1)

    assert first.png == second.png
    assert first.sha256 == second.sha256


def test_resolution_scales_the_output(pdf: Path) -> None:
    low = render_region(pdf, 1, dpi=72)
    high = render_region(pdf, 1, dpi=144)

    assert high.width > low.width
    assert high.height > low.height


def test_different_resolutions_are_different_identities(pdf: Path) -> None:
    """The model reads them differently, so they must not share a cache entry."""
    assert render_region(pdf, 1, dpi=72).sha256 != render_region(pdf, 1, dpi=144).sha256


def test_different_pages_are_different_identities(pdf: Path) -> None:
    assert render_region(pdf, 1).sha256 != render_region(pdf, 2).sha256


def test_a_region_is_smaller_than_its_page_and_identified_separately(pdf: Path) -> None:
    page = render_region(pdf, 1)
    region = render_region(pdf, 1, bbox=(10.0, 10.0, 100.0, 80.0))

    assert region.width < page.width
    assert region.height < page.height
    assert region.sha256 != page.sha256
    assert region.is_whole_page is False


def test_a_box_running_past_the_page_is_clamped_not_refused(pdf: Path) -> None:
    """Layout models report boxes that touch the trim.

    Refusing those would drop exactly the full-bleed drawing sheets this pipeline
    exists to read.
    """
    rendered = render_region(pdf, 1, bbox=(-50.0, -50.0, 10_000.0, 10_000.0))

    assert rendered.width > 0 and rendered.height > 0


@pytest.mark.parametrize("bbox", [(5.0, 5.0, 5.0, 5.0), (5.0, 5.0, 5.0, 40.0)])
def test_a_region_with_no_area_is_refused(
    pdf: Path, bbox: tuple[float, float, float, float]
) -> None:
    """Padding must not turn a region with no content into a sliver of blank page."""
    with pytest.raises(RenderError, match="no area"):
        render_region(pdf, 1, bbox=bbox)


def test_a_page_beyond_the_end_is_refused(pdf: Path) -> None:
    with pytest.raises(RenderError, match="beyond the end"):
        render_region(pdf, 99)


@pytest.mark.parametrize(("page_number", "dpi"), [(0, DEFAULT_DPI), (1, 0), (1, -10)])
def test_invalid_arguments_are_refused(pdf: Path, page_number: int, dpi: int) -> None:
    with pytest.raises(RenderError):
        render_region(pdf, page_number, dpi=dpi)


def test_a_failure_never_carries_the_document_path(tmp_path: Path) -> None:
    """These run on operator documents and the message reaches logs and responses."""
    secret = tmp_path / "client-confidential-borehole-data.pdf"
    secret.write_bytes(b"not a pdf")

    with pytest.raises(RenderError) as caught:
        render_region(secret, 1)

    assert "client-confidential" not in str(caught.value)


def test_the_digest_covers_the_render_version() -> None:
    """A renderer change must retire results cached from images it can no longer make."""
    png = b"\x89PNG\r\n\x1a\npixels"
    current = digest_for(png, dpi=200, bbox=None)

    import document.render as render_module

    original = render_module.RENDER_VERSION
    try:
        render_module.RENDER_VERSION = "r-next"
        assert digest_for(png, dpi=200, bbox=None) != current
    finally:
        render_module.RENDER_VERSION = original

    assert RENDER_VERSION == original
