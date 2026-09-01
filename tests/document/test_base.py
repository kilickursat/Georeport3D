"""The parse contract rejects malformed structure before it reaches the inventory."""

from __future__ import annotations

import math

import pytest

from document.base import ParsedDocument, ParsedFigure, ParsedPage


def test_page_numbers_start_at_one() -> None:
    with pytest.raises(ValueError, match="page_number must be >= 1"):
        ParsedPage(page_number=0)

    with pytest.raises(ValueError, match="page_number must be >= 1"):
        ParsedFigure(page_number=0, kind="figure")


def test_inverted_bbox_is_rejected() -> None:
    with pytest.raises(ValueError, match="bbox maximums"):
        ParsedFigure(page_number=1, kind="figure", bbox=(10.0, 10.0, 5.0, 20.0))


@pytest.mark.parametrize("non_finite", [math.nan, math.inf, -math.inf])
def test_non_finite_bbox_is_rejected(non_finite: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        ParsedFigure(
            page_number=1,
            kind="figure",
            bbox=(non_finite, 10.0, non_finite, 20.0),
        )


def test_figure_must_belong_to_its_page() -> None:
    stray = ParsedFigure(page_number=2, kind="figure")

    with pytest.raises(ValueError, match="figure page_number must match"):
        ParsedPage(page_number=1, figures=(stray,))


def test_duplicate_pages_are_rejected() -> None:
    with pytest.raises(ValueError, match="page numbers must be unique"):
        ParsedDocument(
            source_format="pdf",
            pages=(ParsedPage(page_number=1), ParsedPage(page_number=1)),
        )


def test_pages_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="pages must be ordered"):
        ParsedDocument(
            source_format="pdf",
            pages=(ParsedPage(page_number=2), ParsedPage(page_number=1)),
        )


def test_empty_document_is_valid() -> None:
    assert ParsedDocument(source_format="docx").pages == ()
