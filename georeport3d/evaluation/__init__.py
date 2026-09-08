"""Contracts and diagnostic helpers for cloud-only extraction evaluation."""

from georeport3d.evaluation.manifest import (
    AnnotationStatus,
    DatasetCase,
    DatasetManifest,
    EvaluationMetric,
    SourceFormat,
    load_dataset_manifest,
    require_metric_eligibility,
)
from georeport3d.evaluation.matching import (
    DiagnosticTokenScore,
    canonical_identifier,
    canonical_phrase,
    contains_identifier,
    contains_phrase,
    extract_identifiers,
    score_diagnostic_tokens,
)

__all__ = [
    "AnnotationStatus",
    "DatasetCase",
    "DatasetManifest",
    "DiagnosticTokenScore",
    "EvaluationMetric",
    "SourceFormat",
    "canonical_identifier",
    "canonical_phrase",
    "contains_identifier",
    "contains_phrase",
    "extract_identifiers",
    "load_dataset_manifest",
    "require_metric_eligibility",
    "score_diagnostic_tokens",
]
