"""Deterministic routing hints with no model inference.

This stage decides which regions are worth sending to a vision model, per the AI
router in `docs/04_AI_PIPELINE.md`. It is a routing signal, not a geological claim,
and it never asserts what a figure contains.

Two properties matter more than accuracy here. The result is reproducible, because
the same caption and page text always produce the same classification. And it is
auditable, because every result carries the exact terms that matched, so a reviewer
can see why a region was routed the way it was.

Scores never reach 1.0. Keyword agreement is weak evidence, and a deterministic
matcher must not present itself as certain.

## What changed in v2, and why

Measured against a real 105-page geotechnical baseline report, v1 assigned a
geological identity whenever a term appeared anywhere in a page's text. Every one
of the nineteen regions it labelled `borehole_log` was wrong: each sat on a page of
body prose that merely discussed boring logs, and not one was a borehole log. In a
report of this kind the phrase appears on dozens of narrative pages, so page text
is a reliable indicator of what a page *talks about* and a poor one for what a
region *is*.

So identification now comes only from a region's own caption. Page text can
corroborate a caption, and is recorded as a `hint` when it stands alone, but it can
no longer name a region on its own. A hint is a lead for a reviewer or a later
stage, not a decision.

This makes the stage quieter on purpose. A full-page drawing usually carries no
caption, so it stays at its structural kind and the vision model identifies it -
which is the only approach that works across languages and house styles this
vocabulary does not cover.
"""

from __future__ import annotations

from dataclasses import dataclass

from document.base import FigureKind
from document.terms import TERMS, SourceType, matches, prepare

# Bumped from v1. This value is part of the cache key in
# `georeport3d/services/cache.py`, so changing routing behaviour without bumping it
# would let entries cached under the old behaviour be served as if they were new.
PREPROCESS_VERSION = "v2"

_CAPTION_WEIGHT = 0.8
_CORROBORATED_WEIGHT = 0.9
_ADDITIONAL_TERM_BONUS = 0.05
_MAX_SCORE = 0.95

# Ordered by specificity: the first class with a match wins, so a borehole log is
# not reclassified as a generic section because both vocabularies appear.
_ORDER: tuple[SourceType, ...] = ("borehole_log", "section", "map")


@dataclass(frozen=True)
class Classification:
    """A routing decision plus the evidence that produced it.

    `matched_terms` holds the caption terms that drove identification. `hints` holds
    terms found only in the surrounding page text, which suggest what the page
    discusses without naming the region; `hint_type` is the class they point at.
    """

    source_type: SourceType
    score: float
    matched_terms: tuple[str, ...] = ()
    hints: tuple[str, ...] = ()
    hint_type: SourceType | None = None


def _first_match(prepared: str) -> tuple[SourceType, tuple[str, ...]] | None:
    """Return the most specific class present in prepared text, if any."""
    for source_type in _ORDER:
        found = matches(source_type, prepared)
        if found:
            return source_type, found
    return None


def classify_figure(
    kind: FigureKind,
    caption: str | None = None,
    page_text: str = "",
    *,
    whole_page: bool = False,
) -> Classification:
    """Classify one region from its own caption, using page text only to corroborate.

    `whole_page` marks a region that *is* its page - a full-page engineering drawing
    offered as a region because the layout model detected none. There the distinction
    this module rests on collapses: the page's text is the drawing's own title block,
    not prose about a neighbouring figure, so it identifies rather than merely hints.
    That is what lets a geologic profile sheet be recognised at all, since such sheets
    carry no caption for a caption-only rule to read.
    """
    caption_hit = _first_match(prepare(caption))
    page_hit = _first_match(prepare(page_text))

    if caption_hit is None and whole_page and page_hit is not None:
        source_type, terms = page_hit
        score = min(_MAX_SCORE, _CAPTION_WEIGHT + _ADDITIONAL_TERM_BONUS * (len(terms) - 1))
        return Classification(source_type=source_type, score=score, matched_terms=terms)

    if caption_hit is None:
        # No caption evidence, so no identification. Fall back to the structural kind
        # the parser reported rather than letting page prose name the region, and
        # keep what the page suggests as an auditable lead.
        hints, hint_type = ((), None) if page_hit is None else (page_hit[1], page_hit[0])
        return Classification(
            source_type=kind,
            score=0.0,
            hints=hints,
            hint_type=hint_type,
        )

    source_type, caption_terms = caption_hit
    corroborated = page_hit is not None and page_hit[0] == source_type
    base = _CORROBORATED_WEIGHT if corroborated else _CAPTION_WEIGHT
    score = min(_MAX_SCORE, base + _ADDITIONAL_TERM_BONUS * (len(caption_terms) - 1))

    # Page terms for a *different* class stay visible as a hint; they are why a
    # reviewer might disagree with the caption.
    hints, hint_type = ((), None)
    if page_hit is not None and not corroborated:
        hints, hint_type = page_hit[1], page_hit[0]

    return Classification(
        source_type=source_type,
        score=score,
        matched_terms=caption_terms,
        hints=hints,
        hint_type=hint_type,
    )


__all__ = ["PREPROCESS_VERSION", "TERMS", "Classification", "SourceType", "classify_figure"]
