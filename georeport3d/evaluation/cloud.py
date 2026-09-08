"""Fail-closed paths and artifact handling for Modal-only evaluations."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from pathlib import Path, PurePosixPath

from georeport3d.evaluation.manifest import DatasetCase, load_dataset_manifest

BENCHMARK_ROOT = Path("/benchmarks")
RESULTS_ROOT = Path("/results")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ARTIFACT_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}\.json$")


def validate_run_id(value: str) -> str:
    """Accept one path-safe, bounded run identifier."""
    if not isinstance(value, str) or not _RUN_ID.fullmatch(value) or ".." in value:
        raise ValueError("invalid evaluation run id")
    return value


def resolve_dataset(manifest_path: Path, dataset_id: str) -> tuple[DatasetCase, Path]:
    """Resolve an allow-listed manifest case below the fixed cloud mount."""
    case = load_dataset_manifest(manifest_path).case(dataset_id)
    relative = PurePosixPath(case.cloud_path)
    path = BENCHMARK_ROOT.joinpath(*relative.parts)
    if not path.is_relative_to(BENCHMARK_ROOT):
        raise ValueError("invalid benchmark path")
    return case, path


def verify_dataset_hash(path: Path, expected_sha256: str) -> None:
    """Verify the cloud object before any parser, renderer, or model reads it."""
    if not path.is_file():
        raise RuntimeError("benchmark dataset is not provisioned")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if not hmac.compare_digest(digest.hexdigest(), expected_sha256):
        raise RuntimeError("benchmark dataset failed integrity verification")


def write_raw_cloud_result(run_id: str, artifact_name: str, payload: object) -> Path:
    """Write one non-overwriting raw artifact below the Modal results mount."""
    safe_run_id = validate_run_id(run_id)
    if not _ARTIFACT_NAME.fullmatch(artifact_name):
        raise ValueError("invalid evaluation artifact name")
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
    )
    directory = RESULTS_ROOT / "runs" / safe_run_id
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / artifact_name
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as target:
            target.write(f"{serialized}\n")
    except FileExistsError as exc:
        raise RuntimeError("evaluation artifact already exists") from exc
    return destination
