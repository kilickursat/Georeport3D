# GeoReport3D MVP

Open-source multimodal geotechnical document-to-evidence-to-3D-model foundation.

## What this repository is

GeoReport3D is a coder-ready MVP scaffold for ingesting PDF and DOCX geotechnical reports,
extracting boreholes and geological evidence, validating provenance, storing structured data in
PostGIS, and preparing spatial information for CesiumJS and Three.js visualization.

## Core architecture

- CPU-first document processing.
- Docling adapter for PDF and DOCX inventory.
- Deterministic mock inference for local development and tests.
- Modal serverless GPU inference for production.
- Explicit budget authorization and versioned caching before any GPU call.
- PostGIS as the authoritative project geometry store.
- Provenance-aware evidence with no invented coordinates.

## Production inference target

The production model target is `unsloth/Qwen3.6-27B-NVFP4`, served with vLLM on Modal. The first
deployment target remains one L4 container with scale-to-zero behavior and a maximum of one
container. Production must set `INFERENCE_PROVIDER=modal`; it must never fall back silently to the
mock provider.

Do not download or run the Qwen checkpoint or vLLM on the local workstation. Model weights belong
inside the separately deployed Modal container. Uploading a document only streams, hashes, and
stores it; an upload never starts inference. A later explicit workflow checks cache and budget
before calling Modal.

## Local setup

Use `INFERENCE_PROVIDER=mock` for local development. The following setup commands require an
approved network-capable workstation. They have not completed in this firewall-restricted
workspace, and the firewall must not be bypassed.

```powershell
python -m pip install "uv>=0.8,<1"
uv python install 3.13
uv sync --python 3.13 --extra dev --extra modal
```

Dependency setup installs Python packages and the Modal client SDK; it does not download model
weights. After a successful sync in an approved environment, start the local API with the mock
provider:

```powershell
uv run uvicorn apps.api.app.main:app --reload
```

The local upload route does not invoke the mock provider or Modal automatically.

## Local PostGIS integration (later operator gate)

The Alembic baseline is the database source of truth. Docker and PostGIS were not run in this
offline workspace. On an approved workstation where the pinned image already exists, use:

```powershell
docker compose up -d --pull never db
$env:GEOREPORT3D_RUN_POSTGIS_INTEGRATION='1'
$env:TEST_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/georeport3d_test'
uv run pytest tests/db/test_migrations.py -q -m integration
docker compose stop db
```

The integration test requires both explicit opt-in and a loopback database whose name ends in
`_test`. It rejects shared or production-looking targets without printing credentials. The named
volume is retained by `stop`; `docker compose down -v` deletes local database data and must not be
used without explicit intent. Managed production databases may require a DBA to provision the
PostGIS extension before application migrations run.

## Verification commands

Run these commands only after dependency sync succeeds in an approved network-capable environment:

```powershell
uv run pytest -q
uv run ruff check .
uv run python -m build
uv run python -c "from apps.api.app.main import app; print(app.title, app.version)"
```

The expected API import output is `GeoReport3D API 0.2.0`.

Current offline status on 2026-08-27:

- Recorded source and direct Python 3.13 checks cover the core/API foundation and the code-level
  Modal worker/provider boundary where dependencies were available.
- Lock creation, full dependency sync, pytest, Ruff, the isolated build gate, and the FastAPI import
  remain deferred because their required packages are unavailable in this offline workspace.
- No model was downloaded or loaded, and no inference, Modal deployment, GPU call, FastAPI Cloud
  action, or remote CI job was attempted.

Use the [Modal deployment guide](deployment/README.md) only for a later user-run deployment in an
approved environment. The [pre-deployment readiness audit](docs/19_PRE_DEPLOYMENT_READINESS.md)
classifies intentional fakes, stale artifacts, unwired scaffolds, and the evidence required before
deployment.

## Start here

Read:

1. `docs/00_EXECUTIVE_OVERVIEW.md`
2. `docs/03_IMPLEMENTATION_PLAN.md`
3. `docs/14_CODER_AGENT_INSTRUCTIONS.md`
4. `docs/16_MVP_VERTICAL_SLICE.md`
5. `docs/19_PRE_DEPLOYMENT_READINESS.md`
6. `deployment/README.md`

## Cost target

The hard experimental budget is `$230`. The default policy keeps a reserve and blocks uncontrolled
GPU usage.

## Important limitation

This repository is a foundation, not a finished production application. The document inventory,
database integration, production Modal deployment, and 3D viewer still require their dedicated
implementation and verification steps.
