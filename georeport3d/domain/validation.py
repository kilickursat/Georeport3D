from __future__ import annotations

from pydantic import BaseModel, Field

from georeport3d.domain.models import GeotechnicalExtraction


class ValidationIssue(BaseModel):
    code: str
    message: str
    path: str


class ValidationReport(BaseModel):
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return not self.errors


def validate_extraction(data: GeotechnicalExtraction) -> ValidationReport:
    report = ValidationReport()
    for bh_index, borehole in enumerate(data.boreholes):
        if borehole.total_depth is None or not borehole.intervals:
            continue
        max_depth = max(interval.depth_to for interval in borehole.intervals)
        if max_depth > borehole.total_depth + 0.01:
            report.errors.append(
                ValidationIssue(
                    code="INTERVAL_EXCEEDS_TOTAL_DEPTH",
                    message=(
                        f"{borehole.borehole_id}: interval depth {max_depth} "
                        f"exceeds total depth {borehole.total_depth}"
                    ),
                    path=f"boreholes.{bh_index}.intervals",
                )
            )
    return report
