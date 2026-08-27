"""Create the GeoReport3D PostGIS baseline.

Revision ID: 20260827_0001
Revises:
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision: str = "20260827_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id_column() -> sa.Column[object]:
    return sa.Column("id", sa.Uuid(), primary_key=True, nullable=False)


def _created_at_column() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "projects",
        _id_column(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("crs", sa.String(128)),
        _created_at_column(),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_projects_name_nonempty"),
    )

    op.create_table(
        "documents",
        _id_column(),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        _created_at_column(),
        sa.UniqueConstraint("project_id", "sha256", name="uq_documents_project_sha256"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_documents_size_nonnegative"),
        sa.CheckConstraint(
            "length(trim(original_filename)) > 0",
            name="ck_documents_filename_nonempty",
        ),
        sa.CheckConstraint("length(trim(state)) > 0", name="ck_documents_state_nonempty"),
    )
    op.create_index("ix_documents_project_id", "documents", ["project_id"])
    op.create_index("ix_documents_state", "documents", ["state"])

    op.create_table(
        "boreholes",
        _id_column(),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("borehole_id", sa.String(255), nullable=False),
        sa.Column("easting", sa.Numeric(18, 6)),
        sa.Column("northing", sa.Numeric(18, 6)),
        sa.Column("elevation", sa.Numeric(14, 4)),
        sa.Column("crs", sa.String(128)),
        sa.Column("srid", sa.Integer()),
        sa.Column(
            "geom_project",
            Geometry(geometry_type="POINT", srid=-1, dimension=2, spatial_index=False),
        ),
        sa.Column("total_depth", sa.Numeric(14, 4)),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "project_id", "borehole_id", name="uq_boreholes_project_borehole"
        ),
        sa.CheckConstraint(
            "(easting IS NULL AND northing IS NULL) OR "
            "(easting IS NOT NULL AND northing IS NOT NULL)",
            name="ck_boreholes_paired_xy",
        ),
        sa.CheckConstraint("srid IS NULL OR srid > 0", name="ck_boreholes_srid_positive"),
        sa.CheckConstraint(
            "geom_project IS NULL OR "
            "(easting IS NOT NULL AND northing IS NOT NULL AND "
            "srid IS NOT NULL AND srid > 0)",
            name="ck_boreholes_geometry_has_native_identity",
        ),
        sa.CheckConstraint(
            "geom_project IS NULL OR ST_SRID(geom_project) = srid",
            name="ck_boreholes_geometry_srid_matches",
        ),
        sa.CheckConstraint(
            "total_depth IS NULL OR total_depth >= 0",
            name="ck_boreholes_total_depth_nonnegative",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_boreholes_confidence_range",
        ),
        sa.CheckConstraint(
            "length(trim(borehole_id)) > 0",
            name="ck_boreholes_borehole_id_nonempty",
        ),
    )
    op.create_index("ix_boreholes_project_id", "boreholes", ["project_id"])
    op.create_index(
        "ix_boreholes_geom_project",
        "boreholes",
        ["geom_project"],
        postgresql_using="gist",
    )

    op.create_table(
        "borehole_intervals",
        _id_column(),
        sa.Column(
            "borehole_id",
            sa.Uuid(),
            sa.ForeignKey("boreholes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("depth_from", sa.Numeric(14, 4), nullable=False),
        sa.Column("depth_to", sa.Numeric(14, 4), nullable=False),
        sa.Column("lithology", sa.Text(), nullable=False),
        sa.Column("weathering", sa.Text()),
        sa.Column("rqd", sa.Numeric(7, 3)),
        sa.Column("ucs_mpa", sa.Numeric(12, 3)),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "depth_from >= 0 AND depth_to >= depth_from",
            name="ck_borehole_intervals_depth_order",
        ),
        sa.CheckConstraint(
            "length(trim(lithology)) > 0",
            name="ck_borehole_intervals_lithology_nonempty",
        ),
        sa.CheckConstraint(
            "rqd IS NULL OR (rqd >= 0 AND rqd <= 100)",
            name="ck_borehole_intervals_rqd_range",
        ),
        sa.CheckConstraint(
            "ucs_mpa IS NULL OR ucs_mpa >= 0",
            name="ck_borehole_intervals_ucs_nonnegative",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_borehole_intervals_confidence_range",
        ),
    )
    op.create_index(
        "ix_borehole_intervals_borehole_id", "borehole_intervals", ["borehole_id"]
    )

    op.create_table(
        "evidence",
        _id_column(),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("bbox", postgresql.JSONB()),
        sa.Column("excerpt", sa.Text()),
        sa.Column("model_id", sa.String(255)),
        sa.Column("model_revision", sa.String(255)),
        sa.Column("prompt_version", sa.String(64)),
        sa.Column("preprocess_version", sa.String(64)),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.CheckConstraint("page_number >= 1", name="ck_evidence_page_positive"),
        sa.CheckConstraint(
            "length(trim(source_type)) > 0", name="ck_evidence_source_type_nonempty"
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_evidence_confidence_range",
        ),
    )
    op.create_index("ix_evidence_document_id", "evidence", ["document_id"])

    op.create_table(
        "borehole_evidence",
        sa.Column(
            "borehole_id",
            sa.Uuid(),
            sa.ForeignKey("boreholes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "evidence_id",
            sa.Uuid(),
            sa.ForeignKey("evidence.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "borehole_interval_evidence",
        sa.Column(
            "borehole_interval_id",
            sa.Uuid(),
            sa.ForeignKey("borehole_intervals.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "evidence_id",
            sa.Uuid(),
            sa.ForeignKey("evidence.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "inference_jobs",
        _id_column(),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("model_revision", sa.String(255)),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("preprocess_version", sa.String(64), nullable=False),
        sa.Column("estimated_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("reserved_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("error_code", sa.String(64)),
        _created_at_column(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_inference_jobs_idempotency_key"),
        sa.CheckConstraint(
            "length(trim(state)) > 0", name="ck_inference_jobs_state_nonempty"
        ),
        sa.CheckConstraint(
            "length(trim(provider)) > 0", name="ck_inference_jobs_provider_nonempty"
        ),
        sa.CheckConstraint(
            "estimated_usd >= 0", name="ck_inference_jobs_estimated_usd_nonnegative"
        ),
        sa.CheckConstraint(
            "reserved_usd >= 0", name="ck_inference_jobs_reserved_usd_nonnegative"
        ),
    )
    op.create_index("ix_inference_jobs_document_id", "inference_jobs", ["document_id"])
    op.create_index("ix_inference_jobs_state", "inference_jobs", ["state"])

    op.create_table(
        "usage_records",
        _id_column(),
        sa.Column(
            "inference_job_id",
            sa.Uuid(),
            sa.ForeignKey("inference_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gpu_profile", sa.String(64), nullable=False),
        sa.Column("actual_seconds", sa.Numeric(14, 3), nullable=False),
        sa.Column("actual_usd", sa.Numeric(12, 6), nullable=False),
        _created_at_column(),
        sa.CheckConstraint(
            "actual_seconds >= 0", name="ck_usage_records_actual_seconds_nonnegative"
        ),
        sa.CheckConstraint(
            "actual_usd >= 0", name="ck_usage_records_actual_usd_nonnegative"
        ),
    )
    op.create_index(
        "ix_usage_records_inference_job_id", "usage_records", ["inference_job_id"]
    )

    op.create_table(
        "inference_cache",
        sa.Column("cache_key", sa.String(64), primary_key=True, nullable=False),
        sa.Column("document_sha256", sa.String(64), nullable=False),
        sa.Column("figure_sha256", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("model_revision", sa.String(255)),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("preprocess_version", sa.String(64), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        _created_at_column(),
    )
    op.create_index(
        "ix_inference_cache_document_sha256", "inference_cache", ["document_sha256"]
    )


def downgrade() -> None:
    op.drop_index("ix_inference_cache_document_sha256", table_name="inference_cache")
    op.drop_table("inference_cache")
    op.drop_index("ix_usage_records_inference_job_id", table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_index("ix_inference_jobs_state", table_name="inference_jobs")
    op.drop_index("ix_inference_jobs_document_id", table_name="inference_jobs")
    op.drop_table("inference_jobs")
    op.drop_table("borehole_interval_evidence")
    op.drop_table("borehole_evidence")
    op.drop_index("ix_evidence_document_id", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_borehole_intervals_borehole_id", table_name="borehole_intervals")
    op.drop_table("borehole_intervals")
    op.drop_index("ix_boreholes_geom_project", table_name="boreholes")
    op.drop_index("ix_boreholes_project_id", table_name="boreholes")
    op.drop_table("boreholes")
    op.drop_index("ix_documents_state", table_name="documents")
    op.drop_index("ix_documents_project_id", table_name="documents")
    op.drop_table("documents")
    op.drop_table("projects")
