<p align="center">
  <picture>
    <source
      media="(prefers-color-scheme: dark)"
      srcset="docs/assets/georeport3d-logo-dark-transparent.png"
    >
    <source
      media="(prefers-color-scheme: light)"
      srcset="docs/assets/georeport3d-logo.png"
    >
    <img src="docs/assets/georeport3d-logo.png" alt="GeoReport3D logo" width="820">
  </picture>
</p>

<h1 align="center">GeoReport3D</h1>

<p align="center">
  <strong>Turn geotechnical reports into verifiable 3D ground models — without inventing a single coordinate.</strong>
</p>

<p align="center">
  <a href="https://github.com/kilickursat/Georeport3D/actions/workflows/ci.yml">
    <img alt="CI" src="https://github.com/kilickursat/Georeport3D/actions/workflows/ci.yml/badge.svg">
  </a>
  <a href="LICENSE">
    <img alt="License" src="https://img.shields.io/badge/license-Apache%202.0-blue.svg">
  </a>
  <a href="pyproject.toml">
    <img alt="Python" src="https://img.shields.io/badge/python-3.12%20%7C%203.13-blue.svg">
  </a>
  <a href="docs/19_PRE_DEPLOYMENT_READINESS.md">
    <img alt="Status" src="https://img.shields.io/badge/status-pre--release-orange.svg">
  </a>
</p>

---

Geotechnical ground truth is locked inside PDFs. Borehole logs, cross-sections, and lab tables
are drawn for humans, scattered across hundreds of pages, and rarely survive into a usable
spatial model. GeoReport3D extracts that evidence with a multimodal model, refuses to emit
anything it cannot cite back to a source page, and stores the result as queryable PostGIS
geometry ready for 3D visualization.

The distinguishing constraint is provenance. Every extracted borehole, interval, and contact
carries the document, page, and bounding box it came from, plus a confidence score and an
explicit separation between what was *observed* and what was *inferred*. An extraction with no
evidence is rejected rather than stored.

## Project status

**Pre-release. Not production ready, and not safe to expose publicly.** This repository is an
engineered foundation with verified contracts, not a finished application. The table below is
the honest state; the [pre-deployment readiness audit](docs/19_PRE_DEPLOYMENT_READINESS.md)
carries the full register with per-item evidence requirements.

| Component | State |
| --- | --- |
| Upload, streaming, SHA-256 hashing, bounded storage | Implemented and tested |
| Domain models, evidence and depth validation | Implemented and tested |
| Budget ledger and canonical cache key | Implemented, in-memory only |
| PostGIS schema and Alembic baseline | Migration verified against PostGIS 17-3.5 in CI |
| Modal worker declaration (vLLM, one L4, scale-to-zero) | Declared and contract-tested, never deployed |
| Document pipeline (Docling inventory, figure detection) | Not started |
| Geology (CRS transforms, borehole geometry) | Not started |
| Job orchestration and extraction endpoints | Not started |
| Web application and 3D viewer | Not started |
| Authentication and authorization | Not present |

## How it works

```mermaid
flowchart LR
  U[Upload PDF / DOCX] --> H[SHA-256 + bounded store]
  H --> I[CPU document inventory]
  I --> F[Figure and borehole-log detection]
  F --> C{Cache hit?}
  C -- yes --> V[Validated result]
  C -- no --> B[Budget estimate + explicit authorization]
  B --> M[Modal L4 · Qwen3.6-27B-NVFP4 · vLLM]
  M --> P[Schema + evidence validation]
  P --> V
  V --> D[(PostGIS)]
  D --> W[CesiumJS context + Three.js geometry]
```

Cost governance is structural, not advisory. An upload never triggers inference. Every GPU call
must pass a cache lookup, a workload estimate, and a budget reservation first, and the container
scales to zero with a hard ceiling of one instance.

## Design principles

- **No invented data.** The model may not fabricate coordinates, choose an undocumented CRS,
  interpolate surfaces, or silently reconcile contradictory evidence. Missing values are `null`.
- **Provenance or rejection.** Every observation links to a document, page, and region. Records
  without evidence do not persist.
- **Native coordinates are authoritative.** Original easting/northing and the source CRS are
  preserved. Labelling arbitrary coordinates as WGS84 is treated as a defect, not a shortcut.
- **CPU first.** Text and structured tables are parsed deterministically. The GPU is reserved for
  genuinely visual work such as borehole log figures and cross-sections.
- **Fakes cannot reach production.** The deterministic mock provider is available for development
  and tests, and production startup rejects it outright.

## Quickstart

Requires Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
uv run uvicorn apps.api.app.main:app --reload
```

This runs the API with the deterministic mock inference provider. No model weights are
downloaded, and no GPU or paid service is contacted. Upload streams, hashes, and stores a
document; it never starts inference.

Optional extras: `--extra document` for the Docling pipeline dependencies, `--extra modal` for
the Modal client SDK.

## Development

```bash
uv run ruff check .          # lint
uv run pytest -q             # full suite, GPU-free
uv run python -m build       # isolated package build
```

The PostGIS integration test is opt-in and refuses any target that is not a loopback database
whose name ends in `_test`:

```bash
docker compose up -d db
GEOREPORT3D_RUN_POSTGIS_INTEGRATION=1 \
TEST_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/georeport3d_test' \
uv run pytest -q -m integration
```

Alembic is the authoritative schema; `database/schema.sql` is only a labelled review snapshot.
CI runs every gate above on Python 3.12 and 3.13, plus the migration against a real PostGIS
service container, on each pull request.

## Deployment

Production inference runs on Modal serverless GPU — one L4 container serving
`unsloth/Qwen3.6-27B-NVFP4` under vLLM, pinned to an exact revision, scaling to zero with no
automatic retries. Model weights live inside the Modal container and are never downloaded to a
workstation or a CI runner.

Deployment is manual, gated behind a reviewer approval environment, and never triggered by a
pull request. See the [Modal deployment guide](deployment/README.md) for the operator runbook,
cost boundaries, and the evidence required before and after a deploy.

## Documentation

| Document | Contents |
| --- | --- |
| [Executive overview](docs/00_EXECUTIVE_OVERVIEW.md) | Problem, product shape, and scope |
| [System architecture](docs/02_SYSTEM_ARCHITECTURE.md) | Services, boundaries, and data flow |
| [AI pipeline](docs/04_AI_PIPELINE.md) | Model strategy, routing, prompt requirements, caching |
| [Data contract](docs/05_DATA_CONTRACT.md) | Extraction schema and provenance rules |
| [Modelling and uncertainty](docs/08_GEOTECHNICAL_MODELING_AND_UNCERTAINTY.md) | Observed vs inferred geology |
| [Geospatial and 3D viewer](docs/09_GEOSPATIAL_AND_3D_VIEWER.md) | CesiumJS and Three.js responsibilities |
| [API and job state](docs/10_API_AND_JOB_STATE.md) | Endpoints and the job state machine |
| [Security and data policy](docs/11_SECURITY_AND_DATA_POLICY.md) | Handling confidential reports |
| [Readiness register](docs/19_PRE_DEPLOYMENT_READINESS.md) | Per-item deployment evidence |

## Contributing

Contributions are welcome. Every pull request must keep the CI gates green: Ruff, the full test
suite on both supported Python versions, the isolated build, the API import, and the PostGIS
migration.

Two rules are non-negotiable in review. Extraction code must never produce a coordinate, CRS, or
geological contact that is not traceable to source evidence. Generated artifacts, credentials,
uploaded documents, model weights, and provider logs must never be committed.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
