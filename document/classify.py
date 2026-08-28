"""Deterministic figure classification with no model inference.

This stage decides which regions are worth sending to a vision model, per the AI
router in `docs/04_AI_PIPELINE.md`. It is a routing signal, not a geological claim,
and it never asserts what a figure contains.

Two properties matter more than accuracy here. The result is reproducible, because
the same caption and page text always produce the same classification. And it is
auditable, because every result carries the exact terms that matched, so a reviewer
can see why a region was routed the way it was.

Scores never reach 1.0. Keyword agreement is weak evidence, and a deterministic
matcher must not present itself as certain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from document.base import FigureKind

PREPROCESS_VERSION = "v1"

SourceType = Literal["borehole_log", "section", "map", "table", "figure", "other"]

_CAPTION_WEIGHT = 0.8
_TEXT_WEIGHT = 0.4
_BOTH_WEIGHT = 0.9
_ADDITIONAL_TERM_BONUS = 0.05
_MAX_SCORE = 0.95

# Ordered by specificity: the first class with a match wins, so a borehole log is
# not reclassified as a generic section because both vocabularies appear on a page.
_RULES: tuple[tuple[SourceType, tuple[str, ...]], ...] = (
    (
        "borehole_log",
        (
            "borehole log",
            "bore hole log",
            "borelog",
            "boring log",
            "drillhole log",
            "drill hole log",
            "log of borehole",
            "test pit log",
        ),
    ),
    (
        "section",
        (
            "cross section",
            "cross-section",
            "geological section",
            "geotechnical section",
            "longitudinal section",
            "chainage",
        ),
    ),
    (
        "map",
        (
            "site plan",
            "location plan",
            "borehole location",
            "geological map",
            "plan view",
        ),
    ),
)


@dataclass(frozen=True)
class Classification:
    """A routing decision plus the evidence that produced it."""

    source_type: SourceType
    score: float
    matched_terms: tuple[str, ...] = ()


def _matches(terms: tuple[str, ...], haystack: str) -> tuple[str, ...]:
    return tuple(term for term in terms if term in haystack)


def classify_figure(
    kind: FigureKind,
    caption: str | None = None,
    page_text: str = "",
) -> Classification:
    """Classify one region from its caption and the text surrounding it."""
    caption_text = (caption or "").casefold()
    body_text = page_text.casefold()

    for source_type, terms in _RULES:
        in_caption = _matches(terms, caption_text)
        in_body = _matches(terms, body_text)
        if not in_caption and not in_body:
            continue

        if in_caption and in_body:
            base = _BOTH_WEIGHT
        elif in_caption:
            base = _CAPTION_WEIGHT
        else:
            base = _TEXT_WEIGHT

        matched = tuple(sorted(set(in_caption) | set(in_body)))
        score = min(_MAX_SCORE, base + _ADDITIONAL_TERM_BONUS * (len(matched) - 1))
        return Classification(source_type=source_type, score=score, matched_terms=matched)

    # Nothing matched. Fall back to the structural kind the parser reported rather
    # than guessing a geological meaning the document does not support.
    return Classification(source_type=kind, score=0.0)
