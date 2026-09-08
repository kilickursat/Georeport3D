"""Matching tests use synthetic strings; no report or model output is read."""

from __future__ import annotations

import pytest

from georeport3d.evaluation.manifest import AnnotationStatus
from georeport3d.evaluation.matching import (
    canonical_identifier,
    canonical_phrase,
    contains_identifier,
    contains_phrase,
    extract_identifiers,
    score_diagnostic_tokens,
)


def test_phrase_matching_is_case_punctuation_and_whitespace_tolerant() -> None:
    assert canonical_phrase("  Austin--CHALK ") == "austin chalk"
    assert contains_phrase("Map: AUSTIN\nchalk / Eagle Ford", "austin chalk")


@pytest.mark.parametrize(
    ("expected", "text"),
    [
        ("B-1", "B-10"),
        ("T 1", "T 102"),
        ("sand", "sandstone"),
        ("reach 1", "reach 10"),
        ("B-1", "AB-1"),
        ("B-1", "B-1A"),
    ],
)
def test_prefixes_and_suffixes_do_not_count_as_matches(expected: str, text: str) -> None:
    assert not contains_phrase(text, expected)


@pytest.mark.parametrize("variant", ["B-1", "b 1", "B1", "B - 1", "(b_1)"])
def test_identifier_separator_variants_share_one_canonical_value(variant: str) -> None:
    assert canonical_identifier(variant) == "b1"
    assert contains_identifier(f"read {variant} clearly", "B-1")


def test_adjacent_ocr_fragments_do_not_create_a_prefix_match() -> None:
    text_from_fragments = " ".join(["B", "10", "T", "102"])

    assert not contains_identifier(text_from_fragments, "B-1")
    assert not contains_identifier(text_from_fragments, "T-1")


def test_identifier_extraction_is_boundary_safe_case_insensitive_and_deduplicated() -> None:
    text = "B-1, b 1, B-10, AB-1, T-201, and t 201"

    assert extract_identifiers(text, prefixes=("B", "T")) == ("B-1", "B-10", "T-201")


def test_diagnostic_score_deduplicates_equivalent_expectations() -> None:
    score = score_diagnostic_tokens(
        ["B-1", "b 1", "LIMESTONE", "limestone", "sand"],
        "B1 appears above limestone and sandstone.",
        annotation_status=AnnotationStatus.PROVISIONAL_TOKENS,
    )

    assert score.expected == 3
    assert score.found == 2
    assert score.diagnostic_recall == pytest.approx(2 / 3)
    assert score.matched == ("B-1", "LIMESTONE")
    assert score.missed == ("sand",)
    assert "precision" not in score.model_dump()
    assert score.metric == "diagnostic_token_recall"


def test_unannotated_text_cannot_be_scored_as_token_recall() -> None:
    with pytest.raises(ValueError, match="provisional_tokens or field_gold"):
        score_diagnostic_tokens(
            ["B-1"],
            "B-1",
            annotation_status=AnnotationStatus.UNANNOTATED,
        )


def test_empty_expected_set_emits_no_numeric_recall() -> None:
    score = score_diagnostic_tokens(
        [],
        "arbitrary text",
        annotation_status=AnnotationStatus.PROVISIONAL_TOKENS,
    )

    assert score.expected == 0
    assert score.found == 0
    assert score.diagnostic_recall is None
