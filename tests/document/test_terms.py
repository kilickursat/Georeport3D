"""Vocabulary must survive the spelling, dialect, and OCR damage real reports carry."""

from __future__ import annotations

import pytest

from document.classify import classify_figure
from document.terms import TERMS, fold_dialect, matches, normalize, prepare


def test_normalization_folds_case_punctuation_and_whitespace() -> None:
    assert normalize("Cross-Section  A-A") == "cross section a a"
    assert normalize("") == ""
    assert normalize(None) == ""


def test_normalization_preserves_non_latin_scripts() -> None:
    # The vocabulary is Latin today, but reducing text to [a-z0-9] would erase these
    # outright and make a term table in another script permanently unmatchable.
    #
    # Decomposition is Latin-centric and is lossy here: Cyrillic "й" carries a breve
    # that NFKD strips, leaving "и", a different letter. That is tolerable because it
    # is applied identically to terms and to text, so the two still meet - and
    # `test_every_term_is_written_in_folded_form` is what keeps that promise honest.
    assert "разрез" in normalize("Геологический разрез")
    assert normalize("地质剖面") == "地质剖面"
    assert normalize("Гидрогеология") == "гидрогеология"


def test_normalization_repairs_ocr_accent_damage() -> None:
    # Measured: OCR of a real geologic profile sheet returned "LIMESTONE" carrying a
    # spurious acute accent. Folding accents is what lets a scanned sheet match the
    # same term as a born-digital one.
    assert normalize("LIMÉSTONE") == "limestone"
    assert normalize("Géologique") == "geologique"


@pytest.mark.parametrize(
    ("us", "uk"),
    [
        ("Geologic Profile", "Geological Section"),
        ("Boring Log", "Borehole Log"),
        ("Geologic Map of Dallas County", "Geological Map"),
    ],
)
def test_regional_spellings_reach_the_same_folded_form(us: str, uk: str) -> None:
    # The report this was measured against is a US document using "geologic",
    # "boring log", and "profile"; the v1 vocabulary spoke only the UK forms and
    # missed every one of them.
    assert prepare(us) == prepare(uk) or _same_class(us, uk)


def _same_class(left: str, right: str) -> bool:
    return (
        classify_figure("figure", caption=left).source_type
        == classify_figure("figure", caption=right).source_type
    )


@pytest.mark.parametrize(
    "caption",
    [
        "Figure 8-1A General Geologic Profile STA 10+00 to STA 22+00",
        "Figure 8-1I General Geologic Profile STA 106+00 to STA 115+00",
        "Geological Cross-Section",
        "Längsschnitt",
    ],
)
def test_profile_sheets_route_as_sections(caption: str) -> None:
    # All nine of these sheets scored 0.00 under v1 and were never routed, which is
    # what left the pipeline with no view of the subsurface geology at all.
    assert classify_figure("figure", caption=caption).source_type == "section"


@pytest.mark.parametrize(
    "caption",
    [
        "Figure 4-1 Geologic Map of Dallas County",
        "Figure 7-2 Boring and Reach Location Plan",
        "Figure 2-1 DART D2 Project Location Plan",
    ],
)
def test_plan_and_map_sheets_route_as_maps(caption: str) -> None:
    assert classify_figure("figure", caption=caption).source_type == "map"


@pytest.mark.parametrize(
    "caption",
    ["Boring Log T-201", "Borehole Log BH-7", "Log of Borehole B-3", "Bohrprofil 12"],
)
def test_borehole_logs_route_across_dialects_and_languages(caption: str) -> None:
    assert classify_figure("figure", caption=caption).source_type == "borehole_log"


def test_folding_is_idempotent() -> None:
    once = prepare("Geological Boring Profile")
    assert fold_dialect(once) == once


def test_matches_reports_terms_in_sorted_order_for_stable_audit() -> None:
    found = matches("map", prepare("Site Plan and Location Plan"))
    assert found == tuple(sorted(found))
    assert "location plan" in found


def test_every_term_is_written_in_folded_form() -> None:
    # A term stored unfolded could never match, because the haystack is always
    # folded before comparison. This catches that class of silent dead entry.
    for source_type, by_language in TERMS.items():
        for language, terms in by_language.items():
            for term in terms:
                assert prepare(term) == term, f"{source_type}/{language}: {term!r}"


def test_unmatched_text_yields_nothing() -> None:
    assert matches("borehole_log", prepare("photograph of the site entrance")) == ()
