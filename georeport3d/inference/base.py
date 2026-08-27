"""Provider-neutral inference request and result contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class InferenceRequest:
    """One ordered chat request for structured extraction."""

    messages: list[dict[str, object]]
    max_tokens: int = 2500
    prompt_version: str = "v1"
    preprocess_version: str = "v1"
    model_revision: str | None = None


@dataclass(frozen=True)
class InferenceMetadata:
    """Provider and version identity carried with every result."""

    provider: Literal["mock", "modal"]
    model_id: str
    model_revision: str | None
    prompt_version: str
    preprocess_version: str


@dataclass(frozen=True)
class InferenceFailure:
    """Stable failure details returned by an inference provider."""

    code: str
    message: str


@dataclass(frozen=True)
class InferenceResult:
    """A coherent success or failure envelope."""

    ok: bool
    metadata: InferenceMetadata
    output: dict[str, object] | None = None
    error: InferenceFailure | None = None

    def __post_init__(self) -> None:
        if self.ok:
            if not isinstance(self.output, dict) or self.error is not None:
                raise ValueError(
                    "inference result success requires a dictionary output and no error"
                )
            return
        if self.output is not None or not isinstance(self.error, InferenceFailure):
            raise ValueError(
                "inference result failure requires an InferenceFailure and no output"
            )


@runtime_checkable
class InferenceProvider(Protocol):
    """Synchronous batch extraction boundary implemented by every provider."""

    def extract_batch(
        self,
        requests: Sequence[InferenceRequest],
    ) -> list[InferenceResult]: ...


class InferenceUnavailableError(RuntimeError):
    """Raised when a configured inference provider cannot be reached."""
