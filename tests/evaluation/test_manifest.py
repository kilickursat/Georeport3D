"""Dataset manifests name cloud objects without making local documents test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from georeport3d.evaluation.manifest import (
    AnnotationStatus,
    DatasetCase,
    DatasetManifest,
    EvaluationMetric,
    load_dataset_manifest,
    require_metric_eligibility,
)


def _case(**overrides: object) -> dict[str, object]:
    case: dict[str, object] = {
        "dataset_id": "synthetic-pdf",
        "cloud_path": "reports/synthetic/report.pdf",
        "sha256": "a" * 64,
        "source_format": "pdf",
        "annotation_status": "provisional_tokens",
        "page_selection": [1, 3],
    }
    case.update(overrides)
    return case


@pytest.mark.parametrize(
    "bad_path",
    [
        "../report.pdf",
        "reports/../report.pdf",
        "/reports/report.pdf",
        r"C:\reports\report.pdf",
        r"\\server\share\report.pdf",
        "https://example.test/report.pdf",
    ],
)
def test_cloud_paths_reject_traversal_absolute_paths_and_urls(bad_path: str) -> None:
    with pytest.raises(ValidationError, match="cloud-relative POSIX path"):
        DatasetCase.model_validate(_case(cloud_path=bad_path))


@pytest.mark.parametrize(
    "bad_hash",
    ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, "sha256:" + "a" * 64],
)
def test_sha256_is_exactly_lowercase_hex(bad_hash: str) -> None:
    with pytest.raises(ValidationError, match="64 lowercase hexadecimal"):
        DatasetCase.model_validate(_case(sha256=bad_hash))


def test_source_format_must_match_the_cloud_object_extension() -> None:
    with pytest.raises(ValidationError, match="source_format"):
        DatasetCase.model_validate(_case(source_format="docx"))


@pytest.mark.parametrize("pages", [[0], [2, 1], [1, 1]])
def test_page_selection_is_positive_unique_and_ordered(pages: list[int]) -> None:
    with pytest.raises(ValidationError, match="page_selection"):
        DatasetCase.model_validate(_case(page_selection=pages))


def test_field_gold_requires_a_safe_gold_reference() -> None:
    with pytest.raises(ValidationError, match="gold_reference"):
        DatasetCase.model_validate(_case(annotation_status="field_gold"))

    with pytest.raises(ValidationError, match="cloud-relative POSIX path"):
        DatasetCase.model_validate(
            _case(annotation_status="field_gold", gold_reference="../gold.json")
        )

    case = DatasetCase.model_validate(
        _case(annotation_status="field_gold", gold_reference="gold/synthetic.json")
    )
    assert case.annotation_status is AnnotationStatus.FIELD_GOLD


def test_non_gold_cases_cannot_smuggle_in_a_gold_reference() -> None:
    with pytest.raises(ValidationError, match="only field_gold"):
        DatasetCase.model_validate(_case(gold_reference="gold/not-reviewed.json"))


@pytest.mark.parametrize(
    "metric",
    [
        EvaluationMetric.FIELD_PRECISION,
        EvaluationMetric.FIELD_RECALL,
        EvaluationMetric.FIELD_F1,
        EvaluationMetric.ALL_CRITICAL_FIELDS_CORRECT,
    ],
)
def test_provisional_annotations_cannot_authorize_field_accuracy(metric: EvaluationMetric) -> None:
    case = DatasetCase.model_validate(_case())

    with pytest.raises(ValueError, match="field_gold"):
        require_metric_eligibility(case, metric)


def test_unannotated_cases_cannot_emit_token_accuracy() -> None:
    case = DatasetCase.model_validate(_case(annotation_status="unannotated"))

    with pytest.raises(ValueError, match="provisional_tokens or field_gold"):
        require_metric_eligibility(case, EvaluationMetric.DIAGNOSTIC_TOKEN_RECALL)


def test_field_gold_authorizes_field_metrics() -> None:
    case = DatasetCase.model_validate(
        _case(annotation_status="field_gold", gold_reference="gold/synthetic.json")
    )

    require_metric_eligibility(case, EvaluationMetric.FIELD_PRECISION)


def test_manifest_rejects_duplicate_dataset_ids() -> None:
    with pytest.raises(ValidationError, match="dataset_id values must be unique"):
        DatasetManifest.model_validate({"schema_version": 1, "datasets": [_case(), _case()]})


def test_loader_validates_a_synthetic_yaml_manifest(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"
    path.write_text(
        """
schema_version: 1
datasets:
  - dataset_id: synthetic-docx
    cloud_path: reports/synthetic/report.docx
    sha256: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    source_format: docx
    annotation_status: unannotated
    page_selection: [1]
""".strip(),
        encoding="utf-8",
    )

    manifest = load_dataset_manifest(path)

    assert manifest.datasets[0].dataset_id == "synthetic-docx"
    assert manifest.datasets[0].annotation_status is AnnotationStatus.UNANNOTATED
