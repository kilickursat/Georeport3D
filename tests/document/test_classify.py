"""Deterministic routing must be reproducible, auditable, and never certain."""

from __future__ import annotations

import pytest

from document.classify import classify_figure


def test_caption_match_outranks_page_text_match() -> None:
    from_caption = classify_figure("figure", caption="Borehole Log BH-07")
    from_text = classify_figure("figure", page_text="see the borehole log overleaf")

    assert from_caption.source_type == "borehole_log"
    assert from_text.source_type == "borehole_log"
    assert from_caption.score > from_text.score


def test_agreement_between_caption_and_page_text_scores_highest() -> None:
    both = classify_figure(
        "figure",
        caption="Borehole log",
        page_text="borehole log for BH-07",
    )
    caption_only = classify_figure("figure", caption="Borehole log")

    assert both.score > caption_only.score


def test_score_never_reaches_certainty() -> None:
    saturated = classify_figure(
        "figure",
        caption="borehole log boring log drillhole log test pit log",
        page_text="borehole log boring log drillhole log test pit log borelog",
    )

    assert saturated.score <= 0.95


def test_specific_class_wins_over_general_one() -> None:
    # A page may describe both; the more specific vocabulary must not be lost.
    result = classify_figure(
        "figure",
        caption="Borehole log",
        page_text="cross section along chainage 1200",
    )

    assert result.source_type == "borehole_log"


def test_matched_terms_are_reported_for_audit() -> None:
    result = classify_figure("figure", caption="Cross Section A-A")

    assert result.source_type == "section"
    assert "cross section" in result.matched_terms


def test_classification_is_case_insensitive() -> None:
    upper = classify_figure("figure", caption="BOREHOLE LOG")
    lower = classify_figure("figure", caption="borehole log")

    assert upper == lower


def test_unmatched_region_falls_back_to_structural_kind() -> None:
    figure = classify_figure("figure", caption="Photograph of site entrance")
    table = classify_figure("table", caption="Summary of results")

    assert (figure.source_type, figure.score, figure.matched_terms) == ("figure", 0.0, ())
    assert (table.source_type, table.score) == ("table", 0.0)


def test_missing_caption_and_text_is_not_an_error() -> None:
    assert classify_figure("figure").source_type == "figure"


@pytest.mark.parametrize(
    ("caption", "expected"),
    [
        ("Log of Borehole BH-12", "borehole_log"),
        ("Geological Section", "section"),
        ("Borehole Location Plan", "map"),
    ],
)
def test_representative_captions_route_as_expected(caption: str, expected: str) -> None:
    assert classify_figure("figure", caption=caption).source_type == expected


def test_repeated_calls_are_identical() -> None:
    args = ("figure", "Borehole log BH-1", "chainage and borehole log")
    first = classify_figure(*args)
    second = classify_figure(*args)

    assert first == second
