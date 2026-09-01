"""Immutable production model identity shared by configuration and deployment."""

from __future__ import annotations

import re

_REVISION_PATTERN = re.compile(r"\A[0-9a-f]{40}\Z")


def validate_model_revision(value: object) -> str:
    """Return an immutable commit revision or reject a moving/malformed value."""
    if not isinstance(value, str) or _REVISION_PATTERN.fullmatch(value) is None:
        raise ValueError("model revision must be 40 lowercase hexadecimal characters")
    return value


MODEL_ID = "unsloth/Qwen3.6-27B-NVFP4"
MODEL_REVISION = validate_model_revision(
    "ccdaab7e68af2409599b8949a8f2685703c9bae5"
)
