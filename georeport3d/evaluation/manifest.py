"""Validated references to benchmark objects held outside source control.

The manifest is deliberately metadata-only. Paths are relative to a configured cloud
storage root; accepting URLs or host paths here would turn a dataset selector into an
arbitrary file/network access interface.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_DATASET_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AnnotationStatus(str, Enum):
    """How much human-reviewed truth a dataset case contains."""

    UNANNOTATED = "unannotated"
    PROVISIONAL_TOKENS = "provisional_tokens"
    FIELD_GOLD = "field_gold"


class SourceFormat(str, Enum):
    PDF = "pdf"
    DOCX = "docx"


class EvaluationMetric(str, Enum):
    """Metric names whose eligibility depends on annotation maturity."""

    DIAGNOSTIC_TOKEN_RECALL = "diagnostic_token_recall"
    FIELD_PRECISION = "field_precision"
    FIELD_RECALL = "field_recall"
    FIELD_F1 = "field_f1"
    ALL_CRITICAL_FIELDS_CORRECT = "all_critical_fields_correct"


_FIELD_ACCURACY_METRICS = frozenset(
    {
        EvaluationMetric.FIELD_PRECISION,
        EvaluationMetric.FIELD_RECALL,
        EvaluationMetric.FIELD_F1,
        EvaluationMetric.ALL_CRITICAL_FIELDS_CORRECT,
    }
)


def _cloud_relative_path(value: str) -> str:
    """Return a canonical cloud-relative POSIX path or reject it."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("must be a non-empty cloud-relative POSIX path")
    if "\\" in value or "://" in value or "\x00" in value:
        raise ValueError("must be a cloud-relative POSIX path, not a URL or host path")

    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or any(part in {"", ".", ".."} for part in posix.parts)
        or posix.as_posix() != value
    ):
        raise ValueError("must be a canonical cloud-relative POSIX path without traversal")
    return value


class DatasetCase(BaseModel):
    """One immutable document case selected from private cloud storage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str
    cloud_path: str
    sha256: str
    source_format: SourceFormat
    annotation_status: AnnotationStatus
    page_selection: tuple[int, ...] = Field(min_length=1)
    gold_reference: str | None = None

    @field_validator("dataset_id")
    @classmethod
    def valid_dataset_id(cls, value: str) -> str:
        if not _DATASET_ID.fullmatch(value):
            raise ValueError("dataset_id must be 3-64 lowercase URL-safe characters")
        return value

    @field_validator("cloud_path", "gold_reference")
    @classmethod
    def safe_cloud_path(cls, value: str | None) -> str | None:
        return None if value is None else _cloud_relative_path(value)

    @field_validator("sha256")
    @classmethod
    def valid_sha256(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("sha256 must be exactly 64 lowercase hexadecimal characters")
        return value

    @field_validator("page_selection")
    @classmethod
    def valid_page_selection(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(page < 1 for page in value):
            raise ValueError("page_selection values must be positive")
        if tuple(sorted(set(value))) != value:
            raise ValueError("page_selection must be strictly increasing with no duplicates")
        return value

    @model_validator(mode="after")
    def consistent_annotation_and_format(self) -> DatasetCase:
        expected_suffix = f".{self.source_format.value}"
        if not self.cloud_path.casefold().endswith(expected_suffix):
            raise ValueError("source_format must match the cloud_path extension")

        if self.annotation_status is AnnotationStatus.FIELD_GOLD:
            if self.gold_reference is None:
                raise ValueError("field_gold requires a gold_reference")
        elif self.gold_reference is not None:
            raise ValueError("gold_reference is allowed only for field_gold annotations")
        return self

    @property
    def has_field_gold(self) -> bool:
        return (
            self.annotation_status is AnnotationStatus.FIELD_GOLD
            and self.gold_reference is not None
        )


class DatasetManifest(BaseModel):
    """Versioned collection of uniquely named cloud dataset cases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1, le=1)
    datasets: tuple[DatasetCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_dataset_ids(self) -> DatasetManifest:
        ids = [case.dataset_id for case in self.datasets]
        if len(ids) != len(set(ids)):
            raise ValueError("dataset_id values must be unique")
        return self

    def case(self, dataset_id: str) -> DatasetCase:
        matches = [case for case in self.datasets if case.dataset_id == dataset_id]
        if not matches:
            raise KeyError(f"unknown dataset_id: {dataset_id}")
        return matches[0]


def require_metric_eligibility(case: DatasetCase, metric: EvaluationMetric | str) -> None:
    """Reject an accuracy label that the case's annotations cannot support."""
    metric = EvaluationMetric(metric)
    if metric in _FIELD_ACCURACY_METRICS and not case.has_field_gold:
        raise ValueError(f"{metric.value} requires field_gold with a gold_reference")
    if (
        metric is EvaluationMetric.DIAGNOSTIC_TOKEN_RECALL
        and case.annotation_status is AnnotationStatus.UNANNOTATED
    ):
        raise ValueError("diagnostic_token_recall requires provisional_tokens or field_gold")


def load_dataset_manifest(path: Path) -> DatasetManifest:
    """Load and validate a metadata-only YAML manifest."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return DatasetManifest.model_validate(raw)
