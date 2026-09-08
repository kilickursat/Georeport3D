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
  <strong>Turn geotechnical reports into verifiable 3D ground models - without inventing a single coordinate.</strong>
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
  <a href="https://www.patreon.com/cw/geotechCLI/membership">
    <img alt="Support on Patreon" src="https://img.shields.io/badge/Patreon-support-f96854.svg">
  </a>
</p>

<p align="center">
  <sub>A side project of <strong>geotechCLI</strong>.</sub>
</p>

---

## Pre-release status

**GeoReport3D is not production ready and must not be exposed publicly.** The repository
contains a tested backend foundation and a code-level Modal design, but it does not yet contain
an end-to-end analysis route, a production deployment proven from this revision, or a web/3D
application.

GeoReport3D is designed to turn evidence in geotechnical reports into structured observations.
The central rule is provenance: an accepted borehole, interval, contact, or section must cite
the source document and page region. Missing or unreadable values remain unknown rather than
being guessed.

| Component | Current state |
| --- | --- |
| Upload, project creation, project upload | Implemented; documents are bounded, streamed, hashed, and stored on the local filesystem for development |
| Inventory and estimate API routes | Implemented for PDF/DOCX through the document adapter |
| Job-status API route | Implemented against durable job records |
| Domain schema and validation | Implemented for extractions, evidence, depth rules, and document provenance |
| PostGIS repositories, budget, cache, job state | Implemented and tested; the durable `JobController` enforces cache, authorization, inference, validation, and persistence order |
| Analysis path | Incomplete: `/analyze`, versioned prompt assembly, page rendering/task assembly, cancel, extraction, borehole, section, and page-evidence routes are absent |
| Document representation | The compact Docling inventory is suitable for routing, but is not yet a lossless canonical Docling JSON extraction input |
| DOCX evidence | Semantic inventory is available; pagination is synthetic and fixed-layout visual/page evidence is unsupported |
| Modal production worker | Code-level only: one L40S profile, maximum two containers, bounded startup settings aligned with the successful probe, non-thinking Qwen calls, and vLLM JSON Schema structured output |
| Document evaluation harness | Code-level only: metadata manifest, exact-match diagnostics, private Modal Volumes, and a protected manual workflow; no evaluation was run for this change |
| Extraction accuracy | Unproven: the existing DART case is `provisional_tokens`, not field-level ground truth |
| Geology transforms and observed 3D geometry | Not started |
| Web application and 3D viewer | Not started; no frontend source exists |
| Authentication and authorization | Not present |

Historic `29/30` token recall and `10/18` identifier confirmation figures are not accuracy,
precision, or release evidence. The first came from a narrow provisional token list; the second
used unsafe substring matching. Neither is a current product claim. See the detailed
[document extraction benchmark readiness register](docs/20_DOCUMENT_EXTRACTION_BENCHMARK_READINESS.md)
and the approved [cloud harness design](docs/superpowers/specs/2026-09-08-cloud-document-extraction-harness-design.md).

## Intended flow

```mermaid
flowchart LR
  U["Upload PDF or DOCX"] --> I["CPU document inventory"]
  I --> E["Estimate and explicit authorization"]
  E --> C["Durable cache and JobController"]
  C --> M["Modal L40S: Qwen3.6-27B-FP8"]
  M --> V["Schema, domain, and evidence validation"]
  V --> D[(PostGIS)]
  D --> W["Planned CesiumJS and Three.js viewer"]
```

The upload, inventory, estimate, status, persistence, and controller pieces exist. The API path
that assembles a versioned extraction request and invokes the controller does not. An upload or
estimate therefore cannot start a GPU call today.

## Safety and cloud boundary

- Pull-request CI is GPU-free and receives no Modal or Hugging Face credentials.
- This workflow never downloads model weights or copies reports, page images, OCR text, prompts,
  or raw model output onto developer machines or GitHub runners. The pre-existing ignored local
  test PDF is not opened, uploaded, or recommitted by this change.
- The DART source PDF and prior raw benchmark results are removed from the current tracked tree.
  A normal commit does not erase older Git objects; any history rewrite is a separate maintainer
  decision.
- Paid evaluation is `workflow_dispatch` only, requires the protected `modal-evaluation`
  environment, and returns only a sanitized summary. Production deployment is a separate manual
  workflow.
- Hugging Face access is supplied by the Modal secret `huggingface-secret`. The repository-level
  `HF_TOKEN` is unused by this topology and should be removed or rotated by the repository owner
  after confirming no external workflow relies on it.
- The API's current filesystem store is for local development only. Cloud object storage and
  production data-retention controls remain required.

The [Modal runbook](deployment/README.md) describes the exact data paths, integrity check, manual
evaluation command, and production boundary.

## Quickstart: GPU-free development

Requires Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
uv run uvicorn apps.api.app.main:app --reload
```

The default development provider is deterministic and does not download a model or contact a
GPU service. Uploads go to the configured local development store. Do not run Docling, render
customer documents, or install/model-test the Modal stack on a restricted workstation; use the
reviewed cloud workflow for those workloads.

Optional dependency groups are `document` for Docling and `modal` for the Modal client. They are
not required for the core GPU-free tests.

## Document and evidence limits

PDF pages can carry printed-page evidence when the parser supplies valid page geometry. DOCX is a
flow format in the current adapter: its page ordinals are synthetic, so they cannot be presented
as printed-page evidence. A future Modal-only fixed-layout conversion must record the converter,
version, derivative hash, and coordinate transform before DOCX visual evidence can be accepted.

The current document inventory intentionally condenses Docling output for candidate routing. The
planned extraction path retains canonical Docling JSON, hierarchy, tables, reading order, item
references, and provenance rather than treating flattened page text as ground truth.

## Development gates

```bash
uv run ruff check .
uv run pytest -q
uv run python -m build
```

The full default suite is GPU-free. The PostGIS integration test is opt-in and refuses any target
that is not a loopback database whose name ends in `_test`:

```bash
docker compose up -d db
GEOREPORT3D_RUN_POSTGIS_INTEGRATION=1 \
TEST_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/georeport3d_test' \
uv run pytest -q -m integration
```

Alembic is authoritative; `database/schema.sql` is a labelled review snapshot.

## Modal inference

The production declaration targets `Qwen/Qwen3.6-27B-FP8` at a pinned revision under vLLM on an
L40S. Its startup command now matches the successful probe's CUDA library path, 32,768-token
context limit, 16-sequence limit, and one-image-per-prompt bound. Requests carry the exact
Pydantic response schema; vLLM constrains output to that schema and Qwen thinking mode is
disabled.

Those are source and contract-test facts, not new deployment evidence. This revision has not
built the image, started vLLM, loaded the model, run a document, measured cost, or observed
scale-to-zero. Production remains manual and separate from evaluation.

## Mapping and 3D rendering

The target browser stack is unchanged:

- **CesiumJS and 3D Tiles** provide globe/geospatial context, terrain, coordinate-aware camera
  behavior, and large geospatial datasets.
- **Three.js through React Three Fiber** renders engineering geometry such as boreholes,
  intervals, contacts, sections, and uncertainty overlays.

These responsibilities are planned in [the geospatial and 3D viewer design](docs/09_GEOSPATIAL_AND_3D_VIEWER.md).
There is no `apps/web` implementation yet.

## Documentation

| Document | Contents |
| --- | --- |
| [Executive overview](docs/00_EXECUTIVE_OVERVIEW.md) | Problem, product shape, and scope |
| [System architecture](docs/02_SYSTEM_ARCHITECTURE.md) | Services, boundaries, and data flow |
| [AI pipeline](docs/04_AI_PIPELINE.md) | Routing, prompting, caching, and validation strategy |
| [Data contract](docs/05_DATA_CONTRACT.md) | Extraction schema and provenance rules |
| [API and job state](docs/10_API_AND_JOB_STATE.md) | Target endpoints and state machine |
| [Pre-deployment readiness](docs/19_PRE_DEPLOYMENT_READINESS.md) | Cross-project deployment gates |
| [Extraction benchmark readiness](docs/20_DOCUMENT_EXTRACTION_BENCHMARK_READINESS.md) | Fake, stale, provisional, blocked, and required benchmark state |
| [Cloud harness design](docs/superpowers/specs/2026-09-08-cloud-document-extraction-harness-design.md) | Safe Modal-only extraction evaluation architecture |

## Technology

- API: Python 3.12/3.13, FastAPI, Pydantic, Uvicorn
- Data: PostgreSQL, PostGIS, SQLAlchemy, GeoAlchemy 2, Alembic
- Documents: Docling and python-docx
- Inference: Modal, vLLM, `Qwen/Qwen3.6-27B-FP8`, CUDA
- Tooling: uv, Ruff, pytest, Docker, GitHub Actions
- Planned web: Next.js, React, CesiumJS, Three.js, React Three Fiber

## Contributing

Pull requests must keep the GPU-free CI gates green. Never commit credentials, uploaded reports,
raw OCR/model output, page images, model weights, or generated benchmark artifacts. Extraction
code must not emit coordinates, CRS values, contacts, or other observations without source
evidence.

## Support and acknowledgements

GeoReport3D is an Apache-2.0 side project of **geotechCLI**. If it is useful to you,
[membership on Patreon](https://www.patreon.com/cw/geotechCLI/membership) supports continued
development without changing the project's evidence rules.

The project depends on open-source work including Docling, vLLM, Qwen, PostGIS, SQLAlchemy,
Alembic, FastAPI, Pydantic, uv, Ruff, Modal, CesiumJS, Three.js, and React Three Fiber. Listing a
project records a dependency and gratitude; it does not imply endorsement or support.

## License

Apache License 2.0 - see [LICENSE](LICENSE).
