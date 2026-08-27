"""Public inference provider contracts and local implementations."""

from georeport3d.inference.base import (
    InferenceFailure,
    InferenceMetadata,
    InferenceProvider,
    InferenceRequest,
    InferenceResult,
    InferenceUnavailableError,
)
from georeport3d.inference.mock import MockInferenceProvider
from georeport3d.inference.modal_provider import ModalInferenceProvider

__all__ = [
    "InferenceFailure",
    "InferenceMetadata",
    "InferenceProvider",
    "InferenceRequest",
    "InferenceResult",
    "InferenceUnavailableError",
    "MockInferenceProvider",
    "ModalInferenceProvider",
]
