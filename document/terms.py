"""Vocabulary and text normalization for format-agnostic routing hints.

Geotechnical reports have no standard format. Terminology varies by country, by
company, and by the individual engineer: a US report writes "boring log" and
"geologic profile" where a UK one writes "borehole log" and "geological section",
and a German one writes neither. A fixed list of English phrases cannot be
agnostic, so this module separates three concerns that were previously fused:

  * `normalize` removes the surface variation that carries no meaning - case,
    accents, punctuation, and whitespace. This also repairs a class of real OCR
    damage: a scanned drawing sheet yielded "LIMESTONE" with a spurious accent,
    which normalization folds back onto "limestone".
  * `fold_dialect` maps regional and morphological variants onto one written
    form, so "geological", "geologic", and "geologische" become one token and the
    term table does not have to enumerate every spelling.
  * `TERMS` holds the vocabulary as data, tagged by language, so extending
    coverage to another language or house style is a data change rather than a
    code change.

Terms are written in already-folded form. `matches` folds the haystack the same
way, so the two meet in the middle.

This vocabulary produces *hints*, never conclusions. Deciding what a drawing
actually is belongs to the vision model, which does not depend on the document
being written in a language this table happens to cover.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final, Literal

# `drawing_sheet` is structural, not geological: it says a region is a full sheet the
# layout model found nothing to detect on, and deliberately says nothing about what is
# drawn there. It carries no vocabulary, because it is decided by shape rather than by
# words, which is what lets it hold for a report in a language this table does not cover.
SourceType = Literal[
    "borehole_log", "section", "map", "table", "figure", "drawing_sheet", "other"
]

# Applied to normalized text, longest key first, on word boundaries.
#
# `profile` folds onto `section` deliberately. In geotechnical usage a "geologic
# profile", a "geologic section", and a "geological cross-section" name the same
# artifact - a vertical slice through the ground - and the DART D2 report uses
# "profile" throughout for sheets a UK report would label "section". Folding them
# is a domain judgement, recorded here so it can be revisited rather than
# rediscovered.
# Only equivalences that leave a term still recognisable belong here. Folding a word
# onto a bare generic token such as "plan" or "section" would erase the context that
# made it a term, so words like "Lageplan" stay whole and live in `TERMS` instead.
_DIALECT: Final[dict[str, str]] = {
    # geologic / geological / geologische / geologique / geologico
    "geological": "geologic",
    "geologische": "geologic",
    "geologischer": "geologic",
    "geologisch": "geologic",
    "geologique": "geologic",
    "geologico": "geologic",
    "geologica": "geologic",
    # the borehole family: US "boring", UK "borehole", plus drilling variants
    "borehole": "bore",
    "boreholes": "bore",
    "boring": "bore",
    "borings": "bore",
    "borelog": "bore log",
    "drillhole": "bore",
    "drill hole": "bore",
    "bohrung": "bore",
    "bohrloch": "bore",
    "sondage": "bore",
    "sondeo": "bore",
    "sondaj": "bore",
    # section / profile / cross-section
    "profile": "section",
    "profil": "section",
    "perfil": "section",
    "querschnitt": "section",
    "coupe": "section",
    "kesit": "section",
    # plan / map
    "plano": "plan",
    "karte": "map",
    "carte": "map",
    "mapa": "map",
    "harita": "map",
}

# source type -> language tag -> folded terms.
#
# Language tags are for auditing and for deciding what to extend; matching does
# not depend on them. Ordering of the outer mapping is significant: the first
# type with a match wins, so the most specific vocabulary is listed first and a
# borehole log is not reclassified as a section because both words appear.
TERMS: Final[dict[SourceType, dict[str, tuple[str, ...]]]] = {
    "borehole_log": {
        "en": ("bore log", "log of bore", "test pit log", "trial pit log", "well log"),
        "de": ("bohrprofil", "schichtenverzeichnis"),
        "fr": ("log de bore", "section de bore"),
        "es": ("registro de bore", "columna litologica"),
        "tr": ("bore logu", "bore kutugu"),
    },
    "section": {
        "en": (
            "cross section",
            "geologic section",
            "geotechnical section",
            "longitudinal section",
            "subsurface section",
            "chainage",
            "stationing",
        ),
        "de": ("langsschnitt", "geologic section"),
        # Romance and Turkish word order puts the qualifier after the noun.
        "fr": ("section geologic",),
        "es": ("section geologic",),
        "tr": ("jeolojik section",),
    },
    "map": {
        "en": (
            "site plan",
            "location plan",
            "bore location",
            "geologic map",
            "plan view",
            "key plan",
        ),
        "de": ("uebersichtsplan", "lageplan", "geologic map"),
        "fr": ("plan de situation", "map geologic"),
        "es": ("plan de situacion", "map geologic"),
        "tr": ("vaziyet plan", "jeolojik map"),
    },
}

# Unicode-aware on purpose. Reducing to `[a-z0-9]` would erase Cyrillic, Greek, and
# CJK text outright, so a term table extended to those scripts could never match
# anything. The vocabulary is Latin today; the normalizer does not have to be.
_WORD = re.compile(r"[\W_]+")
_DIALECT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, _DIALECT), key=len, reverse=True)) + r")\b"
)


def normalize(text: str | None) -> str:
    """Casefold, strip accents, and reduce punctuation to single spaces.

    Accent stripping is not cosmetic here. OCR of engineering drawings emits
    spurious diacritics, so folding them is what lets a scanned sheet match the
    same term as a born-digital one.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WORD.sub(" ", without_accents).strip()


def fold_dialect(text: str) -> str:
    """Map regional and morphological variants onto one written form."""
    return _DIALECT_PATTERN.sub(lambda m: _DIALECT[m.group(0)], text)


def prepare(text: str | None) -> str:
    """Normalize and fold in one step, the form terms are written in."""
    return fold_dialect(normalize(text))


def matches(source_type: SourceType, prepared: str) -> tuple[str, ...]:
    """Return the terms of `source_type` present in already-prepared text."""
    if not prepared:
        return ()
    found = {
        term
        for terms in TERMS.get(source_type, {}).values()
        for term in terms
        if term in prepared
    }
    return tuple(sorted(found))
