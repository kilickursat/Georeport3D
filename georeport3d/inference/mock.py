"""Deterministic local inference provider for tests and development."""

from collections.abc import Sequence
from copy import deepcopy

from georeport3d.inference.base import (
    InferenceMetadata,
    InferenceRequest,
    InferenceResult,
)


class MockInferenceProvider:
    """Return isolated copies of one configured fixture without performing inference."""

    def __init__(
        self,
        response: dict[str, object],
        model_id: str = "mock-model",
    ) -> None:
        self._response = deepcopy(response)
        self._model_id = model_id

    def extract_batch(
        self,
        requests: Sequence[InferenceRequest],
    ) -> list[InferenceResult]:
        return [
            InferenceResult(
                ok=True,
                output=deepcopy(self._response),
                metadata=InferenceMetadata(
                    provider="mock",
                    model_id=self._model_id,
                    model_revision=request.model_revision,
                    prompt_version=request.prompt_version,
                    preprocess_version=request.preprocess_version,
                ),
            )
            for request in requests
        ]
