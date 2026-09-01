"""Deterministic routing must be reproducible, auditable, and never certain."""

from __future__ import annotations

import pytest

from document.classify import classify_figure


def test_page_text_alone_cannot_identify_a_region() -> None:
    # v1 let a term anywhere on a page name a region. Measured against a real
    # 105-page baseline report that produced nineteen `borehole_log` regions and
    # nineteen mistakes: each sat on a page of prose that merely discussed boring
    # logs. Page text says what a page is about, not what a region is.
    from_caption = classify_figure("figure", caption="Borehole Log BH-07")
    from_text = classify_figure("figure", page_text="see the borehole log overleaf")

    assert from_caption.source_type == "borehole_log"
    assert from_text.source_type == "figure"
    assert from_text.score == 0.0


def test_page_text_is_kept_as_an_auditable_hint() -> None:
    # Demoting the signal must not discard it: it is still a lead for a reviewer.
    result = classify_figure("figure", page_text="see the borehole log overleaf")

    assert result.hint_type == "borehole_log"
    assert result.hints == ("bore log",)
    assert result.matched_terms == ()


def test_a_whole_page_region_is_a_drawing_sheet_and_its_title_block_only_hints() -> None:
    # v2 typed this `section` off the page text. The vocabulary had not earned that:
    # measured over ten real sheets, most matches came from `stationing`, which says
    # a sheet carries chainages and nothing about what it depicts. The structural
    # fact - a region that is its whole page - is what routes it, and the terms ride
    # along as a lead a reviewer can weigh against what the model reads.
    sheet = classify_figure(
        "figure",
        page_text="GENERAL GEOLOGIC PROFILE STA 46+00 TO STA 58+00 LIMESTONE SHALE",
        whole_page=True,
    )

    assert sheet.source_type == "drawing_sheet"
    assert sheet.hint_type == "section"
    assert sheet.hints == ("geologic section",)
    assert sheet.matched_terms == ()
    assert sheet.score == 0.0


def test_a_sheet_whose_words_are_unknown_still_routes_as_a_drawing_sheet() -> None:
    # The geologic map on p80 and the profile on p89 matched no term at all and were
    # typed `figure` - which is what an ordinary unidentified figure is typed, so the
    # gap did not show. A sheet whose title block is only drawing-office metadata is
    # the same case, and shape routes it without needing a single word recognised.
    sheet = classify_figure(
        "figure",
        page_text="SHEET 12 OF 40   DWG NO C-104   SCALE 1:2000   REV B",
        whole_page=True,
    )

    assert sheet.source_type == "drawing_sheet"
    assert sheet.hint_type is None
    assert sheet.score == 0.0


def test_the_same_text_on_a_normal_region_still_only_hints() -> None:
    # The concession is scoped to regions that are their page. A small figure on a
    # prose page must not borrow the page's subject.
    embedded = classify_figure(
        "figure",
        page_text="GENERAL GEOLOGIC PROFILE STA 46+00 TO STA 58+00 LIMESTONE SHALE",
    )

    assert embedded.source_type == "figure"
    assert embedded.hint_type == "section"


def test_a_caption_still_outranks_page_text_on_a_whole_page_region() -> None:
    result = classify_figure(
        "figure",
        caption="Boring Log T-201",
        page_text="general geologic profile",
        whole_page=True,
    )

    assert result.source_type == "borehole_log"
    assert result.hint_type == "section"


def test_a_caption_contradicted_by_page_text_keeps_the_contradiction_visible() -> None:
    result = classify_figure(
        "figure",
        caption="Borehole log BH-07",
        page_text="site location plan for the northern extent",
    )

    assert result.source_type == "borehole_log"
    assert result.hint_type == "map"


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


def test_strongest_evidence_wins_across_classes() -> None:
    result = classify_figure(
        "figure",
        caption="Geological section A-A",
        page_text="Refer to the borehole log appendix",
    )

    assert result.source_type == "section"
    assert result.score == 0.8
    # Folded to its canonical form, so a US report and a UK one leave the same audit
    # trail rather than two spellings of it.
    assert result.matched_terms == ("geologic section",)
    # And the contradicting page text survives as a lead for a reviewer.
    assert result.hint_type == "borehole_log"


def test_equal_strength_uses_specificity_order() -> None:
    result = classify_figure(
        "figure",
        caption="Borehole log beside geological section",
    )

    assert result.source_type == "borehole_log"
    assert result.score == 0.8
    assert result.matched_terms == ("bore log",)


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
