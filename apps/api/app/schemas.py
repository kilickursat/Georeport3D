from pydantic import BaseModel, Field, field_validator

from georeport3d.domain.models import (
    Borehole,
    BoreholeInterval,
    Collar,
    Evidence,
    GeologicalContact,
    GeotechnicalExtraction,
    Section,
)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    crs: str | None = Field(default=None, max_length=128)

    @field_validator("name")
    @classmethod
    def strip_nonempty_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


__all__ = [
    "Borehole",
    "BoreholeInterval",
    "Collar",
    "Evidence",
    "GeologicalContact",
    "GeotechnicalExtraction",
    "Section",
    "ProjectCreate",
]
