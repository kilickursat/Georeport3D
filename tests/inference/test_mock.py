from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

import georeport3d.inference as public_inference
from georeport3d.inference.base import (
    InferenceFailure,
    InferenceMetadata,
    InferenceProvider,
    InferenceRequest,
    InferenceResult,
    InferenceUnavailableError,
)
from georeport3d.inference.mock import MockInferenceProvider


def metadata() -> InferenceMetadata:
    return InferenceMetadata(
        provider="mock",
        model_id="mock-model",
        model_revision=None,
        prompt_version="v1",
        preprocess_version="v1",
    )


def test_mock_provider_is_deterministic_and_returns_copies() -> None:
    provider = MockInferenceProvider({"boreholes": []}, model_id="mock-model")
    request = InferenceRequest(messages=[{"role": "user", "content": "extract"}])

    first = provider.extract_batch([request])
    assert first[0].output is not None
    first[0].output["boreholes"].append("mutated")  # type: ignore[union-attr]
    second = provider.extract_batch([request])

    assert second[0].output == {"boreholes": []}
    assert second[0].metadata.model_id == "mock-model"
    assert second[0].metadata.prompt_version == "v1"


def test_constructor_fixture_is_deep_copied_immediately() -> None:
    fixture = {"nested": {"values": ["original"]}}
    provider = MockInferenceProvider(fixture)
    fixture["nested"]["values"].append("caller mutation")  # type: ignore[index]

    result = provider.extract_batch([InferenceRequest(messages=[])])

    assert result[0].output == {"nested": {"values": ["original"]}}


def test_batch_items_and_later_calls_have_independent_nested_outputs() -> None:
    provider = MockInferenceProvider({"nested": {"values": ["original"]}})
    requests = [InferenceRequest(messages=[]), InferenceRequest(messages=[])]

    first_batch = provider.extract_batch(requests)
    assert first_batch[0].output is not None
    nested = first_batch[0].output["nested"]
    nested["values"].append("first mutation")  # type: ignore[index]
    second_batch = provider.extract_batch(requests)

    expected = {"nested": {"values": ["original"]}}
    assert first_batch[1].output == expected
    assert second_batch[0].output == expected
    assert second_batch[1].output == expected
    assert first_batch[0].output is not first_batch[1].output
    assert second_batch[0].output is not second_batch[1].output


def test_request_order_and_version_metadata_are_preserved() -> None:
    provider = MockInferenceProvider({"boreholes": []}, model_id="configured-model")
    requests = [
        InferenceRequest(
            messages=[{"role": "user", "content": "first"}],
            model_revision="revision-a",
            prompt_version="prompt-a",
            preprocess_version="preprocess-a",
        ),
        InferenceRequest(
            messages=[{"role": "user", "content": "second"}],
            model_revision="revision-b",
            prompt_version="prompt-b",
            preprocess_version="preprocess-b",
        ),
    ]
    original_messages = deepcopy([request.messages for request in requests])

    results = provider.extract_batch(requests)

    assert [result.metadata.provider for result in results] == ["mock", "mock"]
    assert [result.metadata.model_id for result in results] == [
        "configured-model",
        "configured-model",
    ]
    assert [result.metadata.model_revision for result in results] == [
        "revision-a",
        "revision-b",
    ]
    assert [result.metadata.prompt_version for result in results] == [
        "prompt-a",
        "prompt-b",
    ]
    assert [result.metadata.preprocess_version for result in results] == [
        "preprocess-a",
        "preprocess-b",
    ]
    assert [request.messages for request in requests] == original_messages


def test_request_defaults_match_the_provider_contract() -> None:
    request = InferenceRequest(messages=[])

    assert request.max_tokens == 2500
    assert request.prompt_version == "v1"
    assert request.preprocess_version == "v1"
    assert request.model_revision is None


def test_empty_batch_returns_empty_list() -> None:
    provider = MockInferenceProvider({"boreholes": []})

    assert provider.extract_batch([]) == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"ok": True, "output": None, "error": None},
        {"ok": True, "output": [], "error": None},
        {
            "ok": True,
            "output": {"boreholes": []},
            "error": InferenceFailure(code="failed", message="failure"),
        },
        {"ok": False, "output": {"boreholes": []}, "error": None},
        {"ok": False, "output": None, "error": None},
        {"ok": False, "output": None, "error": {"code": "failed"}},
    ],
)
def test_inference_result_rejects_contradictory_envelopes(
    arguments: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="inference result"):
        InferenceResult(metadata=metadata(), **arguments)  # type: ignore[arg-type]


def test_inference_result_accepts_coherent_success_and_failure() -> None:
    success = InferenceResult(
        ok=True,
        metadata=metadata(),
        output={"boreholes": []},
    )
    failure = InferenceResult(
        ok=False,
        metadata=metadata(),
        error=InferenceFailure(code="invalid_output", message="invalid output"),
    )

    assert success.output == {"boreholes": []}
    assert success.error is None
    assert failure.output is None
    assert failure.error == InferenceFailure(
        code="invalid_output",
        message="invalid output",
    )


@pytest.mark.parametrize(
    ("value", "field", "replacement"),
    [
        (InferenceRequest(messages=[]), "max_tokens", 1),
        (metadata(), "model_id", "other-model"),
        (InferenceFailure(code="failed", message="failure"), "code", "other"),
        (
            InferenceResult(ok=True, metadata=metadata(), output={}),
            "ok",
            False,
        ),
    ],
)
def test_inference_contract_dataclasses_are_frozen(
    value: object,
    field: str,
    replacement: object,
) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(value, field, replacement)


def test_mock_provider_satisfies_runtime_protocol() -> None:
    provider = MockInferenceProvider({"boreholes": []})

    assert isinstance(provider, InferenceProvider)


def test_public_exports_share_the_canonical_class_identities() -> None:
    assert public_inference.InferenceRequest is InferenceRequest
    assert public_inference.InferenceMetadata is InferenceMetadata
    assert public_inference.InferenceFailure is InferenceFailure
    assert public_inference.InferenceResult is InferenceResult
    assert public_inference.InferenceProvider is InferenceProvider
    assert public_inference.InferenceUnavailableError is InferenceUnavailableError
    assert public_inference.MockInferenceProvider is MockInferenceProvider
