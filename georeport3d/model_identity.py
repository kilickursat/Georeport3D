"""Immutable production model identity shared by configuration and deployment."""

from __future__ import annotations

import re

_REVISION_PATTERN = re.compile(r"\A[0-9a-f]{40}\Z")


def validate_model_revision(value: object) -> str:
    """Return an immutable commit revision or reject a moving/malformed value."""
    if not isinstance(value, str) or _REVISION_PATTERN.fullmatch(value) is None:
        raise ValueError("model revision must be 40 lowercase hexadecimal characters")
    return value


# Was `unsloth/Qwen3.6-27B-NVFP4` until this checkpoint was actually run. Unsloth's
# Dynamic NVFP4 keeps most layers at W4A4 rather than W4A16, so it needs Blackwell's
# FP4 tensor cores; on Ada and Hopper vLLM falls back to Marlin, which Unsloth
# documents as causing severe degradation, and which measured at ~36.8 GiB of VRAM
# against 21.8 GiB on disk. vLLM's own recipe for this model names the FP8 build as
# the single-GPU variant for L40S and H100, which is the hardware this project
# deploys on. Same architecture and the same vision capability, no forced kernels.
MODEL_ID = "Qwen/Qwen3.6-27B-FP8"
MODEL_REVISION = validate_model_revision(
    "e89b16ebf1988b3d6befa7de50abc2d76f26eb09"
)
