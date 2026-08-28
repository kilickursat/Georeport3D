-- GENERATED REVIEW SNAPSHOT -- NOT AUTHORITATIVE, DO NOT EXECUTE AS A SCHEMA SCRIPT.
--
-- Source of truth:  Alembic revision 20260827_0001
-- Regenerate with:  uv run alembic upgrade head --sql
--
-- This file exists so the schema can be reviewed in one place. Alembic remains
-- authoritative: apply changes with `alembic upgrade head`, never by running this
-- file. If the two disagree, this file is the stale one and must be regenerated.
--
-- Coordinate note: boreholes.geom_project carries the SRID of the CRS its native
-- easting and northing are already expressed in. It is never a WGS84 relabelling of
-- arbitrary project coordinates, which is the defect that retired the previous
-- hand-written scaffold. ST_SetSRID labels a coordinate, it does not move it.

BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 20260827_0001

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE projects (
    id UUID NOT NULL, 
    name VARCHAR(255) NOT NULL, 
    crs VARCHAR(128), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_projects PRIMARY KEY (id), 
    CONSTRAINT ck_projects_ck_projects_name_nonempty CHECK (length(trim(name)) > 0)
);

CREATE TABLE documents (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    original_filename VARCHAR(512) NOT NULL, 
    sha256 VARCHAR(64) NOT NULL, 
    size_bytes BIGINT NOT NULL, 
    state VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_documents PRIMARY KEY (id), 
    CONSTRAINT uq_documents_project_sha256 UNIQUE (project_id, sha256), 
    CONSTRAINT ck_documents_ck_documents_size_nonnegative CHECK (size_bytes >= 0), 
    CONSTRAINT ck_documents_ck_documents_filename_nonempty CHECK (length(trim(original_filename)) > 0), 
    CONSTRAINT ck_documents_ck_documents_state_nonempty CHECK (length(trim(state)) > 0), 
    CONSTRAINT fk_documents_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE INDEX ix_documents_project_id ON documents (project_id);

CREATE INDEX ix_documents_state ON documents (state);

CREATE TABLE boreholes (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    borehole_id VARCHAR(255) NOT NULL, 
    easting NUMERIC(18, 6), 
    northing NUMERIC(18, 6), 
    elevation NUMERIC(14, 4), 
    crs VARCHAR(128), 
    srid INTEGER, 
    geom_project geometry(POINT,-1), 
    total_depth NUMERIC(14, 4), 
    confidence NUMERIC(5, 4) DEFAULT '0' NOT NULL, 
    CONSTRAINT pk_boreholes PRIMARY KEY (id), 
    CONSTRAINT uq_boreholes_project_borehole UNIQUE (project_id, borehole_id), 
    CONSTRAINT ck_boreholes_ck_boreholes_paired_xy CHECK ((easting IS NULL AND northing IS NULL) OR (easting IS NOT NULL AND northing IS NOT NULL)), 
    CONSTRAINT ck_boreholes_ck_boreholes_srid_positive CHECK (srid IS NULL OR srid > 0), 
    CONSTRAINT ck_boreholes_ck_boreholes_geometry_has_native_identity CHECK (geom_project IS NULL OR (easting IS NOT NULL AND northing IS NOT NULL AND srid IS NOT NULL AND srid > 0)), 
    CONSTRAINT ck_boreholes_ck_boreholes_geometry_srid_matches CHECK (geom_project IS NULL OR ST_SRID(geom_project) = srid), 
    CONSTRAINT ck_boreholes_ck_boreholes_total_depth_nonnegative CHECK (total_depth IS NULL OR total_depth >= 0), 
    CONSTRAINT ck_boreholes_ck_boreholes_confidence_range CHECK (confidence >= 0 AND confidence <= 1), 
    CONSTRAINT ck_boreholes_ck_boreholes_borehole_id_nonempty CHECK (length(trim(borehole_id)) > 0), 
    CONSTRAINT fk_boreholes_project_id_projects FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE INDEX ix_boreholes_project_id ON boreholes (project_id);

CREATE INDEX ix_boreholes_geom_project ON boreholes USING gist (geom_project);

CREATE TABLE borehole_intervals (
    id UUID NOT NULL, 
    borehole_id UUID NOT NULL, 
    depth_from NUMERIC(14, 4) NOT NULL, 
    depth_to NUMERIC(14, 4) NOT NULL, 
    lithology TEXT NOT NULL, 
    weathering TEXT, 
    rqd NUMERIC(7, 3), 
    ucs_mpa NUMERIC(12, 3), 
    confidence NUMERIC(5, 4) DEFAULT '0' NOT NULL, 
    CONSTRAINT pk_borehole_intervals PRIMARY KEY (id), 
    CONSTRAINT ck_borehole_intervals_ck_borehole_intervals_depth_order CHECK (depth_from >= 0 AND depth_to >= depth_from), 
    CONSTRAINT ck_borehole_intervals_ck_borehole_intervals_lithology_nonempty CHECK (length(trim(lithology)) > 0), 
    CONSTRAINT ck_borehole_intervals_ck_borehole_intervals_rqd_range CHECK (rqd IS NULL OR (rqd >= 0 AND rqd <= 100)), 
    CONSTRAINT ck_borehole_intervals_ck_borehole_intervals_ucs_nonnegative CHECK (ucs_mpa IS NULL OR ucs_mpa >= 0), 
    CONSTRAINT ck_borehole_intervals_ck_borehole_intervals_confidence_range CHECK (confidence >= 0 AND confidence <= 1), 
    CONSTRAINT fk_borehole_intervals_borehole_id_boreholes FOREIGN KEY(borehole_id) REFERENCES boreholes (id) ON DELETE CASCADE
);

CREATE INDEX ix_borehole_intervals_borehole_id ON borehole_intervals (borehole_id);

CREATE TABLE evidence (
    id UUID NOT NULL, 
    document_id UUID NOT NULL, 
    page_number INTEGER NOT NULL, 
    source_type VARCHAR(64) NOT NULL, 
    bbox JSONB, 
    excerpt TEXT, 
    model_id VARCHAR(255), 
    model_revision VARCHAR(255), 
    prompt_version VARCHAR(64), 
    preprocess_version VARCHAR(64), 
    confidence NUMERIC(5, 4) DEFAULT '0' NOT NULL, 
    CONSTRAINT pk_evidence PRIMARY KEY (id), 
    CONSTRAINT ck_evidence_ck_evidence_page_positive CHECK (page_number >= 1), 
    CONSTRAINT ck_evidence_ck_evidence_source_type_nonempty CHECK (length(trim(source_type)) > 0), 
    CONSTRAINT ck_evidence_ck_evidence_confidence_range CHECK (confidence >= 0 AND confidence <= 1), 
    CONSTRAINT fk_evidence_document_id_documents FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE INDEX ix_evidence_document_id ON evidence (document_id);

CREATE TABLE borehole_evidence (
    borehole_id UUID NOT NULL, 
    evidence_id UUID NOT NULL, 
    CONSTRAINT pk_borehole_evidence PRIMARY KEY (borehole_id, evidence_id), 
    CONSTRAINT fk_borehole_evidence_borehole_id_boreholes FOREIGN KEY(borehole_id) REFERENCES boreholes (id) ON DELETE CASCADE, 
    CONSTRAINT fk_borehole_evidence_evidence_id_evidence FOREIGN KEY(evidence_id) REFERENCES evidence (id) ON DELETE CASCADE
);

CREATE TABLE borehole_interval_evidence (
    borehole_interval_id UUID NOT NULL, 
    evidence_id UUID NOT NULL, 
    CONSTRAINT pk_borehole_interval_evidence PRIMARY KEY (borehole_interval_id, evidence_id), 
    CONSTRAINT fk_borehole_interval_evidence_borehole_interval_id_bore_bfef FOREIGN KEY(borehole_interval_id) REFERENCES borehole_intervals (id) ON DELETE CASCADE, 
    CONSTRAINT fk_borehole_interval_evidence_evidence_id_evidence FOREIGN KEY(evidence_id) REFERENCES evidence (id) ON DELETE CASCADE
);

CREATE TABLE inference_jobs (
    id UUID NOT NULL, 
    document_id UUID NOT NULL, 
    state VARCHAR(32) NOT NULL, 
    idempotency_key VARCHAR(128) NOT NULL, 
    provider VARCHAR(32) NOT NULL, 
    model_id VARCHAR(255) NOT NULL, 
    model_revision VARCHAR(255), 
    prompt_version VARCHAR(64) NOT NULL, 
    preprocess_version VARCHAR(64) NOT NULL, 
    estimated_usd NUMERIC(12, 6) NOT NULL, 
    reserved_usd NUMERIC(12, 6) NOT NULL, 
    error_code VARCHAR(64), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_inference_jobs PRIMARY KEY (id), 
    CONSTRAINT uq_inference_jobs_idempotency_key UNIQUE (idempotency_key), 
    CONSTRAINT ck_inference_jobs_ck_inference_jobs_state_nonempty CHECK (length(trim(state)) > 0), 
    CONSTRAINT ck_inference_jobs_ck_inference_jobs_provider_nonempty CHECK (length(trim(provider)) > 0), 
    CONSTRAINT ck_inference_jobs_ck_inference_jobs_estimated_usd_nonnegative CHECK (estimated_usd >= 0), 
    CONSTRAINT ck_inference_jobs_ck_inference_jobs_reserved_usd_nonnegative CHECK (reserved_usd >= 0), 
    CONSTRAINT fk_inference_jobs_document_id_documents FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE INDEX ix_inference_jobs_document_id ON inference_jobs (document_id);

CREATE INDEX ix_inference_jobs_state ON inference_jobs (state);

CREATE TABLE usage_records (
    id UUID NOT NULL, 
    inference_job_id UUID NOT NULL, 
    gpu_profile VARCHAR(64) NOT NULL, 
    actual_seconds NUMERIC(14, 3) NOT NULL, 
    actual_usd NUMERIC(12, 6) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_usage_records PRIMARY KEY (id), 
    CONSTRAINT ck_usage_records_ck_usage_records_actual_seconds_nonnegative CHECK (actual_seconds >= 0), 
    CONSTRAINT ck_usage_records_ck_usage_records_actual_usd_nonnegative CHECK (actual_usd >= 0), 
    CONSTRAINT fk_usage_records_inference_job_id_inference_jobs FOREIGN KEY(inference_job_id) REFERENCES inference_jobs (id) ON DELETE CASCADE
);

CREATE INDEX ix_usage_records_inference_job_id ON usage_records (inference_job_id);

CREATE TABLE inference_cache (
    cache_key VARCHAR(64) NOT NULL, 
    document_sha256 VARCHAR(64) NOT NULL, 
    figure_sha256 VARCHAR(64) NOT NULL, 
    model_id VARCHAR(255) NOT NULL, 
    model_revision VARCHAR(255), 
    prompt_version VARCHAR(64) NOT NULL, 
    preprocess_version VARCHAR(64) NOT NULL, 
    result JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_inference_cache PRIMARY KEY (cache_key)
);

CREATE INDEX ix_inference_cache_document_sha256 ON inference_cache (document_sha256);

INSERT INTO alembic_version (version_num) VALUES ('20260827_0001') RETURNING alembic_version.version_num;

COMMIT;

