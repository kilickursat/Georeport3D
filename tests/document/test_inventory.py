"""The inventory must be reproducible and must cite what it routes."""

from __future__ import annotations

import math

import pytest

from document.base import ParsedDocument, ParsedFigure, ParsedPage
from document.classify import PREPROCESS_VERSION
from document.inventory import FigureCandidate, build_inventory


def _document() -> ParsedDocument:
    return ParsedDocument(
        source_format="pdf",
        pages=(
            ParsedPage(
                page_number=1,
                text="Site investigation report",
                figures=(
                    ParsedFigure(
                        page_number=1,
                        kind="figure",
                        bbox=(10.0, 20.0, 30.0, 40.0),
                        caption="Borehole log BH-07",
                    ),
                    ParsedFigure(page_number=1, kind="table", caption="Summary"),
                ),
            ),
            ParsedPage(
                page_number=146,
                text="cross section along chainage 1200",
                figures=(ParsedFigure(page_number=146, kind="figure"),),
            ),
        ),
    )


def test_figure_ids_are_deterministic_and_sortable() -> None:
    first = build_inventory("doc-1", "abc", _document())
    second = build_inventory("doc-1", "abc", _document())

    ids = [figure.figure_id for figure in first.candidates()]
    assert ids == ["p0001-f000", "p0001-f001", "p0146-f000"]
    assert first == second


def test_classification_reaches_the_candidate() -> None:
    inventory = build_inventory("doc-1", "abc", _document())
    log = inventory.candidates("borehole_log")

    assert [figure.figure_id for figure in log] == ["p0001-f000"]
    # Terms are reported in their folded form. "bore log" is the vocabulary entry
    # that matched, and it is what covers "boring log", "borehole log", and
    # "drillhole log" alike, so it says more to a reviewer than the raw substring.
    assert log[0].matched_terms == ("bore log",)
    assert log[0].score > 0.0


def test_page_text_does_not_route_a_figure_without_its_own_caption() -> None:
    # Page 146 discusses a cross section; the uncaptioned figure on it is not
    # thereby a cross section. This is the false positive that produced nineteen
    # wrong `borehole_log` regions on a real report.
    inventory = build_inventory("doc-1", "abc", _document())

    assert inventory.candidates("section") == []


def test_a_page_text_lead_survives_as_a_hint() -> None:
    inventory = build_inventory("doc-1", "abc", _document())
    uncaptioned = [f for f in inventory.candidates() if f.page_number == 146]

    assert uncaptioned[0].hint_type == "section"
    assert uncaptioned[0].source_type == "figure"


def test_candidates_without_a_filter_returns_everything() -> None:
    inventory = build_inventory("doc-1", "abc", _document())

    assert len(inventory.candidates()) == 3


def test_evidence_cites_document_page_and_region() -> None:
    inventory = build_inventory("doc-1", "abc", _document())
    figure = inventory.candidates("borehole_log")[0]

    evidence = inventory.evidence_for(figure)

    assert evidence.document_id == "doc-1"
    assert evidence.page_number == 1
    assert evidence.source_type == "borehole_log"
    assert evidence.bbox == (10.0, 20.0, 30.0, 40.0)
    assert evidence.preprocess_version == PREPROCESS_VERSION


def test_routing_score_is_not_reported_as_extraction_confidence() -> None:
    # docs/05 requires the kinds of confidence to stay separate. A keyword score
    # must never be presented as the system's confidence in an extraction.
    inventory = build_inventory("doc-1", "abc", _document())
    figure = inventory.candidates("borehole_log")[0]

    assert figure.score > 0.0
    assert inventory.evidence_for(figure).confidence == 0.0


def test_inventory_records_document_identity() -> None:
    inventory = build_inventory("doc-1", "sha-256-value", _document())

    assert inventory.document_id == "doc-1"
    assert inventory.sha256 == "sha-256-value"
    assert inventory.source_format == "pdf"
    assert inventory.page_count == 2


def test_page_without_text_is_marked() -> None:
    parsed = ParsedDocument(
        source_format="pdf",
        pages=(ParsedPage(page_number=1, text="   "), ParsedPage(page_number=2, text="x")),
    )
    inventory = build_inventory("doc-1", "abc", parsed)

    assert [page.has_text for page in inventory.pages] == [False, True]


def test_empty_document_produces_an_empty_inventory() -> None:
    inventory = build_inventory("doc-1", "abc", ParsedDocument(source_format="docx"))

    assert inventory.page_count == 0
    assert inventory.candidates() == []


def test_synthetic_pagination_is_carried_into_the_inventory() -> None:
    parsed = ParsedDocument(
        source_format="docx",
        pages=(
            ParsedPage(
                page_number=1,
                text="Borehole log BH-07",
                has_source_pagination=False,
            ),
        ),
        has_source_pagination=False,
    )

    inventory = build_inventory("doc-1", "abc", parsed)

    assert inventory.has_source_pagination is False
    assert inventory.page_count == 1
    assert inventory.pages[0].has_source_pagination is False


def test_pdf_inventory_reports_real_pagination() -> None:
    assert build_inventory("doc-1", "abc", _document()).has_source_pagination is True


def test_mixed_pagination_keeps_real_evidence_and_rejects_synthetic_page_evidence() -> None:
    parsed = ParsedDocument(
        source_format="pdf",
        pages=(
            ParsedPage(
                page_number=1,
                figures=(ParsedFigure(page_number=1, kind="figure", caption="Site plan"),),
            ),
            ParsedPage(
                page_number=2,
                figures=(
                    ParsedFigure(page_number=2, kind="figure", caption="Unplaced appendix"),
                ),
                has_source_pagination=False,
            ),
        ),
        has_source_pagination=False,
    )

    inventory = build_inventory("doc-1", "abc", parsed)

    assert [page.has_source_pagination for page in inventory.pages] == [True, False]
    assert inventory.has_source_pagination is False
    assert inventory.evidence_for(inventory.pages[0].figures[0]).page_number == 1
    with pytest.raises(ValueError, match="synthetic"):
        inventory.evidence_for(inventory.pages[1].figures[0])


@pytest.mark.parametrize("non_finite", [math.nan, math.inf, -math.inf])
def test_candidate_bbox_must_be_finite(non_finite: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        FigureCandidate(
            figure_id="p0001-f000",
            page_number=1,
            source_type="figure",
            score=0.0,
            bbox=(non_finite, 0.0, non_finite, 1.0),
        )
