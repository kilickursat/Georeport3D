# GeoReport3D PostGIS Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the drifting raw SQL scaffold with an authoritative Alembic baseline that preserves native coordinates, links evidence to observations, and records inference jobs, usage, and cache entries.

**Architecture:** SQLAlchemy metadata defines the application schema, Alembic owns migrations, and GeoAlchemy2 declares a mixed-SRID project point without falsely labeling native coordinates as EPSG:4326. Metadata tests run without PostgreSQL; an opt-in integration test upgrades a pinned local PostGIS service.

**Tech Stack:** PostgreSQL 17, PostGIS 3.5, SQLAlchemy 2.x, Alembic, GeoAlchemy2, psycopg 3, Docker Compose, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-phase-0-stabilization-design.md`

## Global Constraints

- Native easting, northing, elevation, and CRS remain authoritative and nullable.
- Easting and northing must be both null or both non-null.
- Geometry is created only when coordinates and a numeric SRID are known.
- Native/project coordinates are not labeled EPSG:4326 unless they are actually WGS84.
- Evidence has explicit links to boreholes and intervals.
- Alembic is authoritative; `database/schema.sql` is only a generated, labeled snapshot.
- Normal unit tests do not require PostgreSQL, PostGIS, Modal, or a GPU.
- The local integration service uses `postgis/postgis:17-3.5`, an upstream-recommended stable image as of 2026-08-27.
- Git metadata is absent. Do not initialize a repository; use verification checkpoints.

## Verified Primary Reference

- Docker PostGIS supported tags: `https://github.com/postgis/docker-postgis`

## File Map

- `georeport3d/db/base.py`: declarative base and naming convention.
- `georeport3d/db/models.py`: authoritative table metadata.
- `alembic.ini`: Alembic command configuration.
- `migrations/env.py`: settings-aware migration environment.
- `migrations/versions/20260827_0001_baseline.py`: initial schema.
- `compose.yaml`: local PostgreSQL/PostGIS integration service.
- `database/schema.sql`: clearly labeled snapshot produced from the baseline.
- `tests/db/test_metadata.py`: no-database schema invariants.
- `tests/db/test_migrations.py`: opt-in real PostGIS migration test.

---

### Task 1: Migration Tooling and Local PostGIS Service

**Files:**
- Modify: `pyproject.toml`
- Create: `georeport3d/db/__init__.py`
- Create: `georeport3d/db/base.py`
- Create: `alembic.ini`
- Create: `migrations/script.py.mako`
- Create: `migrations/env.py`
- Create: `compose.yaml`
- Create: `tests/db/test_migration_config.py`

**Interfaces:**
- Produces: `georeport3d.db.base.Base`
- Produces: `uv run alembic upgrade head`
- Produces local DB URL: `postgresql+psycopg://postgres:postgres@localhost:5432/georeport3d`

- [ ] **Step 1: Write a failing migration configuration test**

```python
from pathlib import Path

from alembic.config import Config


def test_alembic_configuration_points_to_migrations() -> None:
    config = Config("alembic.ini")
    assert config.get_main_option("script_location") == "migrations"
    assert Path("migrations/env.py").is_file()
```

- [ ] **Step 2: Confirm red state**

Run: `uv run pytest tests/db/test_migration_config.py -q`

Expected: FAIL because Alembic is not installed and configuration files do not exist.

- [ ] **Step 3: Add migration dependencies**

Add these runtime dependencies to `pyproject.toml`:

```toml
"alembic>=1.16,<2",
"geoalchemy2>=0.18,<1",
```

Run: `uv lock && uv sync --python 3.13 --extra dev --extra modal`

- [ ] **Step 4: Add deterministic SQLAlchemy naming**

```python
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

- [ ] **Step 5: Configure Alembic from application settings**

`alembic.ini` sets `script_location = migrations` and contains no password-bearing URL. In `migrations/env.py`, import all models and preserve a URL explicitly supplied by tests or the CLI; otherwise load `Settings().database_url`:

```python
if not config.get_main_option("sqlalchemy.url"):
    settings = Settings()
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
target_metadata = Base.metadata
```

Implement standard offline and online migration functions using `engine_from_config(..., prefix="sqlalchemy.", poolclass=pool.NullPool)` and `context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)`.

- [ ] **Step 6: Add the pinned local service**

```yaml
services:
  db:
    image: postgis/postgis:17-3.5
    environment:
      POSTGRES_DB: georeport3d
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d georeport3d"]
      interval: 2s
      timeout: 5s
      retries: 30
    volumes:
      - georeport3d-postgis:/var/lib/postgresql/data

volumes:
  georeport3d-postgis:
```

Document that these credentials are local-development defaults only.

- [ ] **Step 7: Run migration configuration test**

Run: `uv run pytest tests/db/test_migration_config.py -q`

Expected: PASS.

- [ ] **Step 8: Record checkpoint**

Suggested commit if Git metadata is restored: `build: add Alembic and local PostGIS tooling`.

---

### Task 2: Authoritative Observation, Evidence, Job, Usage, and Cache Schema

**Files:**
- Create: `georeport3d/db/models.py`
- Modify: `georeport3d/db/__init__.py`
- Create: `migrations/versions/20260827_0001_baseline.py`
- Create: `tests/db/test_metadata.py`

**Interfaces:**
- Produces tables: `projects`, `documents`, `boreholes`, `borehole_intervals`, `evidence`, `borehole_evidence`, `borehole_interval_evidence`, `inference_jobs`, `usage_records`, `inference_cache`
- Produces PostGIS column: `boreholes.geom_project geometry(POINT)` with no fixed SRID

- [ ] **Step 1: Write failing metadata tests**

```python
from geoalchemy2 import Geometry

from georeport3d.db.base import Base
from georeport3d.db import models  # noqa: F401


def test_baseline_tables_are_complete() -> None:
    assert set(Base.metadata.tables) == {
        "projects",
        "documents",
        "boreholes",
        "borehole_intervals",
        "evidence",
        "borehole_evidence",
        "borehole_interval_evidence",
        "inference_jobs",
        "usage_records",
        "inference_cache",
    }


def test_project_geometry_is_not_falsely_wgs84() -> None:
    column = Base.metadata.tables["boreholes"].c.geom_project
    assert isinstance(column.type, Geometry)
    assert column.type.geometry_type == "POINT"
    assert column.type.srid == -1


def test_evidence_links_have_real_foreign_keys() -> None:
    links = Base.metadata.tables["borehole_interval_evidence"]
    targets = {fk.target_fullname for fk in links.foreign_keys}
    assert targets == {"borehole_intervals.id", "evidence.id"}
```

- [ ] **Step 2: Confirm red state**

Run: `uv run pytest tests/db/test_metadata.py -q`

Expected: FAIL because table models do not exist.

- [ ] **Step 3: Implement common ID and timestamp patterns**

Every entity ID uses `Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)`. Creation timestamps use timezone-aware `DateTime(timezone=True)` with `server_default=func.now()`.

Use these exact entity responsibilities:

```text
projects: id, name, crs, created_at
documents: id, project_id, original_filename, sha256, size_bytes, state, created_at
boreholes: id, project_id, borehole_id, easting, northing, elevation, crs, srid, geom_project, total_depth, confidence
borehole_intervals: id, borehole_id, depth_from, depth_to, lithology, weathering, rqd, ucs_mpa, confidence
evidence: id, document_id, page_number, source_type, bbox JSON, excerpt, model_id, model_revision, prompt_version, preprocess_version, confidence
borehole_evidence: borehole_id, evidence_id
borehole_interval_evidence: borehole_interval_id, evidence_id
inference_jobs: id, document_id, state, idempotency_key, provider, model_id, model_revision, prompt_version, preprocess_version, estimated_usd, reserved_usd, error_code, created_at, updated_at
usage_records: id, inference_job_id, gpu_profile, actual_seconds, actual_usd, created_at
inference_cache: cache_key, document_sha256, figure_sha256, model_id, model_revision, prompt_version, preprocess_version, result JSON, created_at
```

- [ ] **Step 4: Add deterministic constraints**

Add named checks:

```python
CheckConstraint(
    "(easting IS NULL AND northing IS NULL) OR (easting IS NOT NULL AND northing IS NOT NULL)",
    name="paired_xy",
)
CheckConstraint("depth_from >= 0 AND depth_to >= depth_from", name="depth_order")
CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range")
CheckConstraint("rqd IS NULL OR (rqd >= 0 AND rqd <= 100)", name="rqd_range")
```

Use `Geometry(geometry_type="POINT", srid=-1, dimension=2, spatial_index=True)` for `geom_project`. Make easting, northing, elevation, CRS, SRID, and geometry nullable. Add uniqueness for `(project_id, borehole_id)`, `(project_id, sha256)`, and `inference_jobs.idempotency_key`.

- [ ] **Step 5: Define the baseline migration explicitly**

Create revision ID `20260827_0001`, `down_revision = None`. `upgrade()` first executes `CREATE EXTENSION IF NOT EXISTS postgis`, then creates tables in foreign-key order and indexes the hash, state, job idempotency key, cache key, and geometry. `downgrade()` drops application tables in reverse order but does not drop the shared PostGIS extension.

Do not autogenerate and accept blindly. Compare every migration column and constraint with `Base.metadata` before running it.

- [ ] **Step 6: Run metadata tests**

Run: `uv run pytest tests/db/test_metadata.py -q`

Expected: PASS without a database connection.

- [ ] **Step 7: Validate migration Python syntax**

Run: `uv run python -m compileall -q georeport3d/db migrations`

Expected: exit 0.

- [ ] **Step 8: Record checkpoint**

Suggested commit if Git metadata is restored: `feat: add the authoritative PostGIS baseline`.

---

### Task 3: Real PostGIS Upgrade Test and Schema Snapshot

**Files:**
- Create: `tests/db/test_migrations.py`
- Modify: `pyproject.toml`
- Replace: `database/schema.sql`
- Modify: `README.md`
- Modify: `docs/15_DEVELOPER_CHECKLIST.md`

**Interfaces:**
- Consumes: environment variable `TEST_DATABASE_URL`
- Produces: verified `alembic upgrade head` and clearly labeled SQL snapshot

- [ ] **Step 1: Register the integration marker**

Add to `pyproject.toml`:

```toml
markers = ["integration: requires an external service such as PostGIS"]
```

- [ ] **Step 2: Write the migration integration test**

```python
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


@pytest.mark.integration
def test_upgrade_head_creates_postgis_schema() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT PostGIS_Version()")).scalar_one()
        tables = set(inspect(connection).get_table_names())
    assert {"projects", "documents", "boreholes", "evidence", "inference_jobs"} <= tables
```

- [ ] **Step 3: Start the pinned service**

Run:

```powershell
docker compose up -d db
docker compose ps
```

Expected: service `db` reports healthy. Do not remove the named volume during normal verification.

- [ ] **Step 4: Run the real migration test**

Run:

```powershell
$env:TEST_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/georeport3d'
uv run pytest tests/db/test_migrations.py -q -m integration
```

Expected: PASS and PostGIS version is queryable.

- [ ] **Step 5: Generate and label the schema snapshot**

Run Alembic's offline SQL generation:

```powershell
uv run alembic upgrade head --sql
```

Capture the output in `database/schema.sql` using the shell's normal file redirection during execution. Prepend:

```sql
-- Generated from Alembic revision 20260827_0001.
-- Read-only reference snapshot; migrations are authoritative.
```

Do not hand-edit schema behavior only in this snapshot.

- [ ] **Step 6: Run full database and static verification**

Run:

```powershell
uv run pytest tests/db -q
uv run ruff check georeport3d/db migrations tests/db
uv run alembic heads
```

Expected: tests pass, Ruff exits 0, and Alembic prints exactly `20260827_0001 (head)`.

- [ ] **Step 7: Document lifecycle commands**

README documents `docker compose up -d db`, `uv run alembic upgrade head`, and `docker compose stop db`. State that `docker compose down -v` deletes local database data and must not be used without explicit intent.

- [ ] **Step 8: Update checklist from evidence**

Mark “PostgreSQL/PostGIS schema applies” complete only after Step 4 passes. Leave persistence of actual extracted boreholes unchecked until application repositories are implemented.

- [ ] **Step 9: Record checkpoint**

Suggested commit if Git metadata is restored: `test: verify the PostGIS baseline migration`.
