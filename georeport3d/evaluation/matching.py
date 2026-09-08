"""Boundary-safe matching and explicitly diagnostic token scoring."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from document.terms import normalize
from georeport3d.evaluation.manifest import AnnotationStatus

# Applied to normalized text, so punctuation is already a space. A maximum prefix
# length avoids treating arbitrary prose such as "section 1" as an identifier.
_IDENTIFIER = re.compile(
    r"(?<!\w)(?P<prefix>[^\W\d_]{1,4})\s*(?P<number>\d{1,4})(?!\w)",
    re.UNICODE,
)


def canonical_phrase(value: str) -> str:
    """Normalize a phrase while retaining token boundaries."""
    return normalize(value)


def _identifier_parts(value: str) -> tuple[str, str] | None:
    match = _IDENTIFIER.fullmatch(canonical_phrase(value))
    if match is None:
        return None
    return match.group("prefix"), match.group("number")


def canonical_identifier(value: str) -> str:
    """Canonicalize a complete identifier, tolerating separator variation only."""
    parts = _identifier_parts(value)
    if parts is None:
        raise ValueError(f"not an identifier: {value!r}")
    return "".join(parts)


def _identifiers_in(text: str) -> tuple[tuple[str, str], ...]:
    normalized = canonical_phrase(text)
    return tuple(
        (match.group("prefix"), match.group("number"))
        for match in _IDENTIFIER.finditer(normalized)
    )


def contains_identifier(text: str, expected: str) -> bool:
    """Match a complete identifier without prefix/suffix collisions."""
    parts = _identifier_parts(expected)
    if parts is None:
        raise ValueError(f"not an identifier: {expected!r}")
    return parts in _identifiers_in(text)


def contains_phrase(text: str, expected: str) -> bool:
    """Match a normalized phrase as a complete token sequence.

    Identifier-shaped phrases additionally tolerate missing/changed separators while
    still requiring an exact prefix and numeric component.
    """
    if _identifier_parts(expected) is not None:
        return contains_identifier(text, expected)

    needle = tuple(canonical_phrase(expected).split())
    if not needle:
        return False
    haystack = tuple(canonical_phrase(text).split())
    width = len(needle)
    return any(
        haystack[start : start + width] == needle
        for start in range(len(haystack) - width + 1)
    )


def extract_identifiers(text: str, *, prefixes: Iterable[str]) -> tuple[str, ...]:
    """Extract unique identifiers for an explicit, domain-owned prefix allowlist."""
    allowed = {canonical_phrase(prefix) for prefix in prefixes}
    found: dict[str, str] = {}
    for prefix, number in _identifiers_in(text):
        if prefix not in allowed:
            continue
        canonical = f"{prefix}{number}"
        found.setdefault(canonical, f"{prefix.upper()}-{number}")
    return tuple(found.values())


class DiagnosticTokenScore(BaseModel):
    """Recall-oriented signal that deliberately contains no precision field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: Literal["diagnostic_token_recall"] = "diagnostic_token_recall"
    annotation_status: AnnotationStatus
    expected: int = Field(ge=0)
    found: int = Field(ge=0)
    diagnostic_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    matched: tuple[str, ...]
    missed: tuple[str, ...]


def _match_key(value: str) -> tuple[str, str]:
    identifier = _identifier_parts(value)
    if identifier is not None:
        return "identifier", "".join(identifier)
    phrase = canonical_phrase(value)
    if not phrase:
        raise ValueError("expected diagnostic tokens must not be empty")
    return "phrase", phrase


def score_diagnostic_tokens(
    expected: Iterable[str],
    text: str,
    *,
    annotation_status: AnnotationStatus | str,
) -> DiagnosticTokenScore:
    """Score unique hand-verified tokens without implying field-level accuracy."""
    status = AnnotationStatus(annotation_status)
    if status is AnnotationStatus.UNANNOTATED:
        raise ValueError("diagnostic token recall requires provisional_tokens or field_gold")

    unique: dict[tuple[str, str], str] = {}
    for token in expected:
        unique.setdefault(_match_key(token), token)

    matched = tuple(token for token in unique.values() if contains_phrase(text, token))
    missed = tuple(token for token in unique.values() if not contains_phrase(text, token))
    expected_count = len(unique)
    found_count = len(matched)
    recall = found_count / expected_count if expected_count else None
    return DiagnosticTokenScore(
        annotation_status=status,
        expected=expected_count,
        found=found_count,
        diagnostic_recall=recall,
        matched=matched,
        missed=missed,
    )
