from __future__ import annotations

from pathlib import Path

import pytest

from georeport3d.evaluation.cloud import resolve_dataset, validate_run_id


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config" / "evaluation_datasets.yaml"


def test_manifest_dataset_resolves_only_below_the_fixed_cloud_mount() -> None:
    case, path = resolve_dataset(MANIFEST, "dart-d2-cbd2-gbr-v1")

    assert path.as_posix() == "/benchmarks/dart-d2/cbd2_20per_geotechnicalbaselinereport.pdf"
    assert case.annotation_status.value == "provisional_tokens"


@pytest.mark.parametrize(
    "value",
    ["", "ab", "../escape", "run/child", "run id", ".hidden", "a" * 129],
)
def test_run_id_rejects_unsafe_or_unbounded_values(value: str) -> None:
    with pytest.raises(ValueError, match="invalid evaluation run id"):
        validate_run_id(value)


def test_run_id_accepts_the_github_actions_shape() -> None:
    value = f"{'a' * 40}-12345-1"
    assert validate_run_id(value) == value
