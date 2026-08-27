"""Authoritative SQLAlchemy metadata for observations, provenance, jobs, and cache."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from georeport3d.db.base import Base


def _uuid_column() -> Mapped[UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid4)


def _created_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = _uuid_column()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    crs: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = _created_at_column()

    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="name_nonempty"),)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = _uuid_column()
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = _created_at_column()

    __table_args__ = (
        UniqueConstraint("project_id", "sha256", name="uq_documents_project_sha256"),
        CheckConstraint("size_bytes >= 0", name="size_nonnegative"),
        CheckConstraint("length(trim(original_filename)) > 0", name="filename_nonempty"),
        CheckConstraint("length(trim(state)) > 0", name="state_nonempty"),
        Index("ix_documents_project_id", "project_id"),
        Index("ix_documents_state", "state"),
    )


class Borehole(Base):
    __tablename__ = "boreholes"

    id: Mapped[UUID] = _uuid_column()
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    borehole_id: Mapped[str] = mapped_column(String(255), nullable=False)
    easting: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    northing: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    elevation: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    crs: Mapped[str | None] = mapped_column(String(128))
    srid: Mapped[int | None] = mapped_column(Integer)
    geom_project: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=-1, dimension=2, spatial_index=False)
    )
    total_depth: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, server_default="0"
    )

    __table_args__ = (
        UniqueConstraint("project_id", "borehole_id", name="uq_boreholes_project_borehole"),
        CheckConstraint(
            "(easting IS NULL AND northing IS NULL) OR "
            "(easting IS NOT NULL AND northing IS NOT NULL)",
            name="paired_xy",
        ),
        CheckConstraint("srid IS NULL OR srid > 0", name="srid_positive"),
        CheckConstraint(
            "geom_project IS NULL OR "
            "(easting IS NOT NULL AND northing IS NOT NULL AND srid IS NOT NULL AND srid > 0)",
            name="geometry_has_native_identity",
        ),
        CheckConstraint(
            "geom_project IS NULL OR ST_SRID(geom_project) = srid",
            name="geometry_srid_matches",
        ),
        CheckConstraint("total_depth IS NULL OR total_depth >= 0", name="total_depth_nonnegative"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("length(trim(borehole_id)) > 0", name="borehole_id_nonempty"),
        Index("ix_boreholes_project_id", "project_id"),
        Index("ix_boreholes_geom_project", "geom_project", postgresql_using="gist"),
    )


class BoreholeInterval(Base):
    __tablename__ = "borehole_intervals"

    id: Mapped[UUID] = _uuid_column()
    borehole_id: Mapped[UUID] = mapped_column(
        ForeignKey("boreholes.id", ondelete="CASCADE"), nullable=False
    )
    depth_from: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    depth_to: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    lithology: Mapped[str] = mapped_column(Text, nullable=False)
    weathering: Mapped[str | None] = mapped_column(Text)
    rqd: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    ucs_mpa: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, server_default="0"
    )

    __table_args__ = (
        CheckConstraint("depth_from >= 0 AND depth_to >= depth_from", name="depth_order"),
        CheckConstraint("length(trim(lithology)) > 0", name="lithology_nonempty"),
        CheckConstraint("rqd IS NULL OR (rqd >= 0 AND rqd <= 100)", name="rqd_range"),
        CheckConstraint("ucs_mpa IS NULL OR ucs_mpa >= 0", name="ucs_nonnegative"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        Index("ix_borehole_intervals_borehole_id", "borehole_id"),
    )


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[UUID] = _uuid_column()
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    bbox: Mapped[dict[str, object] | list[object] | None] = mapped_column(JSONB)
    excerpt: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(String(255))
    model_revision: Mapped[str | None] = mapped_column(String(255))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    preprocess_version: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, server_default="0"
    )

    __table_args__ = (
        CheckConstraint("page_number >= 1", name="page_positive"),
        CheckConstraint("length(trim(source_type)) > 0", name="source_type_nonempty"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        Index("ix_evidence_document_id", "document_id"),
    )


class BoreholeEvidence(Base):
    __tablename__ = "borehole_evidence"

    borehole_id: Mapped[UUID] = mapped_column(
        ForeignKey("boreholes.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True
    )


class BoreholeIntervalEvidence(Base):
    __tablename__ = "borehole_interval_evidence"

    borehole_interval_id: Mapped[UUID] = mapped_column(
        ForeignKey("borehole_intervals.id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[UUID] = mapped_column(
        ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True
    )


class InferenceJob(Base):
    __tablename__ = "inference_jobs"

    id: Mapped[UUID] = _uuid_column()
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    model_revision: Mapped[str | None] = mapped_column(String(255))
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    preprocess_version: Mapped[str] = mapped_column(String(64), nullable=False)
    estimated_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created_at_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("length(trim(state)) > 0", name="state_nonempty"),
        CheckConstraint("length(trim(provider)) > 0", name="provider_nonempty"),
        CheckConstraint("estimated_usd >= 0", name="estimated_usd_nonnegative"),
        CheckConstraint("reserved_usd >= 0", name="reserved_usd_nonnegative"),
        Index("ix_inference_jobs_document_id", "document_id"),
        Index("ix_inference_jobs_state", "state"),
    )


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[UUID] = _uuid_column()
    inference_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("inference_jobs.id", ondelete="CASCADE"), nullable=False
    )
    gpu_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    actual_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    actual_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    created_at: Mapped[datetime] = _created_at_column()

    __table_args__ = (
        CheckConstraint("actual_seconds >= 0", name="actual_seconds_nonnegative"),
        CheckConstraint("actual_usd >= 0", name="actual_usd_nonnegative"),
        Index("ix_usage_records_inference_job_id", "inference_job_id"),
    )


class InferenceCache(Base):
    __tablename__ = "inference_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    figure_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    model_revision: Mapped[str | None] = mapped_column(String(255))
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    preprocess_version: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created_at_column()

    __table_args__ = (Index("ix_inference_cache_document_sha256", "document_sha256"),)
