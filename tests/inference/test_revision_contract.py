"""The served model revision must equal the one the job was authorized under.

`model_revision` is one of the six fields the cache key is derived from. If the
revision a result was actually produced under can differ from the revision recorded
against it, then a result gets stored under a key that does not identify the model
that produced it, and is later served for work it never did. No later validation can
detect that, because both halves look internally consistent.

Three points have to agree, and each is checked here against the mistake that would
break it: configuration cannot name an unpinned revision, the worker refuses a
request for a revision it is not serving, and the provider refuses a result whose
metadata claims a different revision than was asked for.

Written after the plan's task A2 found the contract already implemented across #14
but nowhere asserted as *rejection* behaviour, which is the part that regresses
quietly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from georeport3d.config import Settings
from georeport3d.inference.base import InferenceRequest, InferenceUnavailableError
from georeport3d.inference.modal_provider import ModalInferenceProvider
from georeport3d.model_identity import MODEL_ID, MODEL_REVISION


def _load_helpers(*names: str) -> dict[str, object]:
    """Borrow the worker-helper loader from the Modal contract tests.

    Loaded by path rather than imported: `tests/modal` shadows the installed `modal`
    SDK on the import path, so `modal.test_worker` resolves to the wrong package.
    """
    path = Path(__file__).resolve().parents[1] / "modal" / "test_worker.py"
    spec = importlib.util.spec_from_file_location("_worker_contract_helpers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._load_helpers(*names)

OTHER_REVISION = "0" * 40


# -- configuration ---------------------------------------------------------------


def test_settings_carry_the_pinned_revision_rather_than_nothing() -> None:
    """The default is the pinned commit, not None.

    It was None once, which meant the CPU side derived every cache key from a value
    that named no model at all.
    """
    assert Settings(app_env="test").model_revision == MODEL_REVISION


@pytest.mark.parametrize("moving", ["main", "latest", "", "HEAD", "abc123", MODEL_REVISION.upper()])
def test_a_moving_or_malformed_revision_is_refused(moving: str) -> None:
    """A tag can be repointed at different weights; a commit cannot."""
    with pytest.raises(ValueError, match="40 lowercase hexadecimal"):
        Settings(app_env="test", model_revision=moving)


def test_production_cannot_deviate_from_the_source_controlled_identity() -> None:
    with pytest.raises(ValueError):
        Settings(
            app_env="production",
            inference_provider="modal",
            model_revision=OTHER_REVISION,
        )


# -- the worker ------------------------------------------------------------------


def test_the_worker_refuses_a_request_for_a_revision_it_does_not_serve() -> None:
    """The container serves one pinned revision and must not answer for another.

    Without this the worker would happily label another revision's output with the
    requested one, which is the mislabelling this whole contract exists to prevent.
    """
    validate = _load_helpers()["_validate_request"]
    request = {
        "messages": [{"role": "user", "content": "extract"}],
        "max_tokens": 128,
        "model_revision": OTHER_REVISION,
        "prompt_version": "v1",
        "preprocess_version": "v1",
    }

    with pytest.raises(ValueError, match="invalid request"):
        validate(request)  # type: ignore[operator]

    # The same request differing only in revision is accepted, so the rejection is
    # attributable to the revision rather than to anything else in the payload.
    accepted = validate({**request, "model_revision": MODEL_REVISION})  # type: ignore[operator]
    assert accepted[2] == MODEL_REVISION


# -- the provider ----------------------------------------------------------------


class _Worker:
    """A worker returning metadata the caller controls, standing in for a bad build."""

    def __init__(self, metadata: dict[str, object]) -> None:
        self._metadata = metadata
        self.extract_batch = self

    def remote(self, payload: list[dict[str, object]]) -> list[dict[str, object]]:
        return [
            {"ok": True, "output": {"document_id": "doc-1"}, "metadata": self._metadata}
            for _ in payload
        ]


def _provider(metadata: dict[str, object]) -> ModalInferenceProvider:
    worker = _Worker(metadata)
    return ModalInferenceProvider(
        app_name="georeport3d-qwen",
        class_name="QwenWorker",
        model_id=MODEL_ID,
        resolver=lambda: worker,
    )


def _request(revision: str = MODEL_REVISION) -> InferenceRequest:
    return InferenceRequest(
        messages=[{"role": "user", "content": "extract"}],
        max_tokens=128,
        prompt_version="v1",
        preprocess_version="v1",
        model_revision=revision,
    )


def _metadata(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "provider": "modal",
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "prompt_version": "v1",
        "preprocess_version": "v1",
    }
    base.update(overrides)
    return base


def test_a_matching_revision_is_accepted() -> None:
    """The negative cases below mean nothing without this one."""
    results = _provider(_metadata()).extract_batch([_request()])

    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].metadata.model_revision == MODEL_REVISION


@pytest.mark.parametrize(
    "bad",
    [
        {"model_revision": OTHER_REVISION},
        {"model_id": "someone/else"},
        {"prompt_version": "v-other"},
        {"preprocess_version": "v-other"},
        {"provider": "mock"},
    ],
)
def test_a_result_claiming_a_different_identity_is_refused(bad: dict[str, object]) -> None:
    """Every field the cache key is built from has to match, not just the revision.

    A result accepted under the wrong value for any of them is cached under a key
    that does not describe it.
    """
    with pytest.raises(InferenceUnavailableError):
        _provider(_metadata(**bad)).extract_batch([_request()])
