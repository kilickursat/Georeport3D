"""CPU-side boundary for explicit Modal serverless inference."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
from typing import Protocol, cast

from georeport3d.inference.base import (
    InferenceFailure,
    InferenceMetadata,
    InferenceRequest,
    InferenceResult,
    InferenceUnavailableError,
)

_FAILURE_MESSAGES = {
    "INVALID_REQUEST": "request was invalid",
    "INVALID_MODEL_JSON": "model output was not valid JSON",
    "INFERENCE_FAILED": "inference request failed",
}


class _RemoteMethod(Protocol):
    def remote(self, payload: list[dict[str, object]]) -> object: ...


class _Worker(Protocol):
    extract_batch: _RemoteMethod


def _invalid_response() -> InferenceUnavailableError:
    return InferenceUnavailableError("Modal worker returned an invalid response")


class ModalInferenceProvider:
    """Invoke one named Modal class without importing the SDK locally at startup."""

    def __init__(
        self,
        app_name: str,
        class_name: str,
        model_id: str,
        resolver: Callable[[], object] | None = None,
    ) -> None:
        identities = {
            "app_name": app_name,
            "class_name": class_name,
            "model_id": model_id,
        }
        for name, value in identities.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")

        self._app_name = app_name
        self._class_name = class_name
        self._model_id = model_id
        self._resolver = resolver if resolver is not None else self._resolve

    def _resolve(self) -> object:
        """Resolve the deployed class only when a non-empty batch needs it."""
        try:
            import modal
        except ImportError as exc:
            raise InferenceUnavailableError("Modal SDK is not installed") from exc

        worker_class = modal.Cls.from_name(self._app_name, self._class_name)
        return worker_class()

    def extract_batch(
        self,
        requests: Sequence[InferenceRequest],
    ) -> list[InferenceResult]:
        """Send one ordered batch and validate the untrusted remote envelopes."""
        request_items = list(requests)
        if not request_items:
            return []

        payload = [
            {
                "messages": deepcopy(request.messages),
                "max_tokens": request.max_tokens,
                "model_revision": request.model_revision,
                "prompt_version": request.prompt_version,
                "preprocess_version": request.preprocess_version,
            }
            for request in request_items
        ]
        try:
            worker = cast(_Worker, self._resolver())
        except InferenceUnavailableError:
            raise
        except Exception as exc:
            raise InferenceUnavailableError("Modal worker is unavailable") from exc

        try:
            raw_results = worker.extract_batch.remote(payload)
        except Exception as exc:
            raise InferenceUnavailableError("Modal worker is unavailable") from exc

        if not isinstance(raw_results, list) or len(raw_results) != len(request_items):
            raise _invalid_response()

        return [
            self._to_result(request, raw)
            for request, raw in zip(request_items, raw_results, strict=True)
        ]

    def _to_result(
        self,
        request: InferenceRequest,
        raw: object,
    ) -> InferenceResult:
        if not isinstance(raw, dict):
            raise _invalid_response()

        if raw.get("ok") is True:
            return self._to_success(request, raw)
        if raw.get("ok") is False:
            return self._to_failure(request, raw)
        raise _invalid_response()

    def _to_success(
        self,
        request: InferenceRequest,
        raw: dict[object, object],
    ) -> InferenceResult:
        output = raw.get("output")
        metadata = raw.get("metadata")
        if not isinstance(output, dict) or "error" in raw or not isinstance(metadata, dict):
            raise _invalid_response()

        required_metadata = {
            "provider",
            "model_id",
            "model_revision",
            "prompt_version",
            "preprocess_version",
        }
        if not required_metadata.issubset(metadata):
            raise _invalid_response()

        returned_model_id = metadata["model_id"]
        versions_match = (
            metadata["model_revision"] == request.model_revision
            and metadata["prompt_version"] == request.prompt_version
            and metadata["preprocess_version"] == request.preprocess_version
        )
        if (
            metadata["provider"] != "modal"
            or not isinstance(returned_model_id, str)
            or not returned_model_id.strip()
            or returned_model_id != self._model_id
            or not versions_match
        ):
            raise _invalid_response()

        result_metadata = self._metadata(request, returned_model_id)
        return InferenceResult(ok=True, output=output, metadata=result_metadata)

    def _to_failure(
        self,
        request: InferenceRequest,
        raw: dict[object, object],
    ) -> InferenceResult:
        error = raw.get("error")
        if "output" in raw or not isinstance(error, dict):
            raise _invalid_response()

        code = error.get("code")
        if not isinstance(code, str) or code not in _FAILURE_MESSAGES:
            raise _invalid_response()

        return InferenceResult(
            ok=False,
            error=InferenceFailure(code=code, message=_FAILURE_MESSAGES[code]),
            metadata=self._metadata(request, self._model_id),
        )

    @staticmethod
    def _metadata(request: InferenceRequest, model_id: str) -> InferenceMetadata:
        return InferenceMetadata(
            provider="modal",
            model_id=model_id,
            model_revision=request.model_revision,
            prompt_version=request.prompt_version,
            preprocess_version=request.preprocess_version,
        )
