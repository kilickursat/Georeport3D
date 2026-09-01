from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Evidence(BaseModel):
    document_id: str
    page_number: int = Field(ge=1)
    source_type: Literal[
        "text",
        "table",
        "figure",
        "borehole_log",
        "section",
        "map",
        # A full drawing sheet whose subject has not been determined. Recorded as its
        # own kind rather than as `figure` so that a citation cannot read as a settled
        # identification when nothing identified it.
        "drawing_sheet",
        "other",
    ]
    bbox: tuple[float, float, float, float] | None = None
    excerpt: str | None = None
    model_id: str | None = None
    model_revision: str | None = None
    prompt_version: str | None = None
    preprocess_version: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def ordered_bbox(self) -> Evidence:
        if self.bbox is not None and not all(math.isfinite(value) for value in self.bbox):
            raise ValueError("bbox values must be finite")
        if self.bbox is not None and (
            self.bbox[2] < self.bbox[0] or self.bbox[3] < self.bbox[1]
        ):
            raise ValueError("bbox maximums must be >= minimums")
        return self


class Collar(BaseModel):
    easting: float | None = None
    northing: float | None = None
    elevation: float | None = None
    crs: str | None = None

    @model_validator(mode="after")
    def paired_xy(self) -> Collar:
        if (self.easting is None) != (self.northing is None):
            raise ValueError("easting and northing must both be present or both be absent")
        return self


class BoreholeInterval(BaseModel):
    depth_from: float = Field(ge=0)
    depth_to: float = Field(ge=0)
    lithology: str = Field(min_length=1)
    weathering: str | None = None
    rqd: float | None = Field(default=None, ge=0, le=100)
    ucs_mpa: float | None = Field(default=None, ge=0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(min_length=1)

    @model_validator(mode="after")
    def depth_order(self) -> BoreholeInterval:
        if self.depth_to < self.depth_from:
            raise ValueError("depth_to must be >= depth_from")
        return self


class Borehole(BaseModel):
    borehole_id: str
    collar: Collar | None = None
    total_depth: float | None = Field(default=None, ge=0)
    intervals: list[BoreholeInterval] = Field(default_factory=list)
    evidence: list[Evidence] = Field(min_length=1)


class GeologicalContact(BaseModel):
    contact_id: str
    unit_a: str
    unit_b: str
    geometry_2d: list[list[float]] | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    inferred: bool = False
    evidence: list[Evidence] = Field(min_length=1)


class Section(BaseModel):
    section_id: str
    start_xy: list[float] | None = None
    end_xy: list[float] | None = None
    elevation_range: list[float] | None = None
    chainage_range: list[float] | None = None
    borehole_ids: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(min_length=1)


class GeotechnicalExtraction(BaseModel):
    document_id: str
    boreholes: list[Borehole] = Field(default_factory=list)
    contacts: list[GeologicalContact] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
