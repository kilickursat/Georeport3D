from pathlib import Path

import pytest
from pydantic import ValidationError

from georeport3d.config import Policy, Settings, load_policy
from georeport3d.model_identity import MODEL_ID, MODEL_REVISION

CANONICAL_CACHE_KEY_FIELDS = [
    "document_sha256",
    "figure_sha256",
    "model_id",
    "model_revision",
    "prompt_version",
    "preprocess_version",
]


def _valid_policy_data() -> dict[str, object]:
    return {
        "budget": {
            "global_usd": 230,
            "default_job_cap_usd": 5,
            "require_confirmation_above_usd": 1,
            "hard_stop_usd": 220,
        },
        "limits": {
            "max_file_mb": 250,
            "max_pages": 500,
            "max_ai_pages_per_job": 100,
            "max_concurrent_gpu_jobs": 1,
        },
        "cache": {
            "enabled": True,
            "key_fields": CANONICAL_CACHE_KEY_FIELDS.copy(),
        },
        "modal": {
            "gpu": "L40S",
            "min_containers": 0,
            "max_containers": 2,
            "buffer_containers": 0,
            "scaledown_window_seconds": 10,
            "timeout_seconds": 900,
        },
    }


def test_repository_policy_loads() -> None:
    policy = load_policy(Path("config/policy.yaml"))
    assert policy.budget.global_usd == 230
    assert policy.budget.hard_stop_usd == 220
    assert policy.cache.key_fields == CANONICAL_CACHE_KEY_FIELDS
    assert policy.modal.gpu == "L40S"
    assert policy.modal.min_containers == 0
    assert policy.modal.max_containers == 2
    assert policy.modal.buffer_containers == 0


def test_policy_rejects_hard_stop_above_global_budget() -> None:
    policy_data = _valid_policy_data()
    budget = policy_data["budget"]
    assert isinstance(budget, dict)
    budget["global_usd"] = 10
    budget["hard_stop_usd"] = 11

    with pytest.raises(ValidationError, match="hard_stop_usd"):
        Policy.model_validate(policy_data)


def test_production_cannot_default_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("INFERENCE_PROVIDER", "mock")
    with pytest.raises(ValidationError, match="mock"):
        Settings()


@pytest.mark.parametrize(
    "override",
    [
        pytest.param({"model_id": "other/model"}, id="model-id"),
        pytest.param({"model_revision": "0" * 40}, id="model-revision"),
    ],
)
def test_modal_settings_reject_identity_init_overrides(
    override: dict[str, str],
) -> None:
    with pytest.raises(ValidationError, match="source-controlled model identity"):
        Settings(_env_file=None, inference_provider="modal", **override)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        pytest.param("MODEL_ID", "other/model", id="model-id"),
        pytest.param("MODEL_REVISION", "0" * 40, id="model-revision"),
    ],
)
def test_modal_settings_reject_identity_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv("INFERENCE_PROVIDER", "modal")
    monkeypatch.setenv("MODEL_ID", MODEL_ID)
    monkeypatch.setenv("MODEL_REVISION", MODEL_REVISION)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match="source-controlled model identity"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "modal_override",
    [
        pytest.param({"min_containers": 1}, id="nonzero-minimum"),
        pytest.param({"max_containers": 3}, id="too-many-containers"),
        pytest.param({"buffer_containers": 1}, id="nonzero-buffer"),
    ],
)
def test_policy_rejects_non_phase_zero_modal_scaling(
    modal_override: dict[str, int],
) -> None:
    policy_data = _valid_policy_data()
    modal = policy_data["modal"]
    assert isinstance(modal, dict)
    modal.update(modal_override)

    with pytest.raises(ValidationError):
        Policy.model_validate(policy_data)


@pytest.mark.parametrize(
    "key_fields",
    [
        pytest.param(
            [
                "document_sha256",
                "figure_sha256",
                "model_id",
                "prompt_version",
                "preprocess_version",
            ],
            id="missing-model-revision",
        ),
        pytest.param(
            [
                "document_sha256",
                "figure_sha256",
                "model_id",
                "model_revision",
                "model_revision",
                "prompt_version",
                "preprocess_version",
            ],
            id="duplicate-model-revision",
        ),
        pytest.param(
            [
                "document_sha256",
                "figure_sha256",
                "model_id",
                "model_revision",
                "prompt_version",
                "preprocess_version",
                "unknown_field",
            ],
            id="unknown-field",
        ),
        pytest.param(
            [
                "figure_sha256",
                "document_sha256",
                "model_id",
                "model_revision",
                "prompt_version",
                "preprocess_version",
            ],
            id="reordered-fields",
        ),
    ],
)
def test_policy_rejects_noncanonical_cache_key_fields(key_fields: list[str]) -> None:
    policy_data = _valid_policy_data()
    cache = policy_data["cache"]
    assert isinstance(cache, dict)
    cache["key_fields"] = key_fields

    with pytest.raises(ValidationError, match="key_fields"):
        Policy.model_validate(policy_data)
