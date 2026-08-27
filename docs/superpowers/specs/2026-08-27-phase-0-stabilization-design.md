# GeoReport3D Phase 0 Stabilization Design

Date: 2026-08-27
Status: Approved in chat; written specification pending user review

## Purpose

Stabilize the current scaffold so it is installable, internally consistent, testable, and locally runnable before building the Docling inventory and 3D viewer. Modal serverless GPU inference remains a required part of the architecture.

The stabilization resolves the confirmed package collision, centralizes policy, strengthens provenance and coordinate handling, makes uploads durable, provides a deterministic test provider, and creates explicit boundaries between the API, core domain, storage, and Modal deployment.

## Non-negotiable requirements

1. Production multimodal inference runs on Modal serverless GPU.
2. The first deployment target remains one L4 container with scale-to-zero behavior.
3. Uploading a document never starts GPU work automatically.
4. The API checks cache and budget before invoking Modal.
5. Missing coordinates remain missing; no layer may invent them.
6. Accepted AI observations have source evidence.
7. Normal tests and local development do not require a GPU or Modal credentials.
8. Document contents and secrets are not logged.

## Scope

### Included

- Python package and build configuration.
- Removal of the local-package collision with the official Modal SDK.
- Central settings and policy loading.
- Core extraction models and deterministic validation.
- Cost authorization and cache-key behavior.
- Streaming, hashing, and local persistence for uploads.
- Inference-provider interface with deterministic mock and Modal implementations.
- Repair of the initial PostGIS schema and migration boundary.
- API dependency injection and tests.
- Modal worker import/deployment smoke checks that do not launch paid inference.
- Updated developer documentation and commands.

### Deferred

- Real Docling parsing and figure detection.
- A full asynchronous job controller.
- Production object storage.
- Geological interpolation and uncertainty fields.
- The CesiumJS/Three.js frontend.
- A paid end-to-end GPU benchmark. This requires explicit operator intent and a real test document.

## Architecture

The repository will use an installable core package and keep deployment code outside names that collide with third-party libraries.

```text
georeport3d/
  config.py
  domain/
    models.py
    validation.py
  services/
    budget.py
    cache.py
  storage/
    base.py
    local.py
  inference/
    base.py
    mock.py
    modal_provider.py

apps/api/app/
  main.py
  dependencies.py

deployment/
  modal_worker.py

tests/
```

The existing local `modal/` directory will be replaced by `deployment/`. The official `modal` package will remain an optional runtime dependency, and `deployment/modal_worker.py` will continue to use `import modal`.

The intended production flow is:

```text
upload -> local/object storage -> CPU inventory -> cache lookup
       -> budget authorization -> Modal Function.remote()
       -> vLLM/Qwen extraction -> strict validation -> PostGIS
```

Phase 0 implements the upload, policy, provider, validation, and deployable-worker boundaries. The CPU inventory and database-backed job orchestration follow in later phases.

## Packaging and runtime

`pyproject.toml` will define an explicit build backend and package discovery. Runtime support remains Python 3.12 and 3.13. A development extra will include pytest, pytest-cov, Ruff, build tooling, HTTP test support, and the Modal SDK without container-only GPU dependencies. `uv` is the environment and lock tool; `uv.lock` will make local and CI dependency resolution reproducible.

The package version and FastAPI version will use one source. Commands for editable install, API startup, tests, linting, build verification, and Modal deployment will be documented.

## Configuration

Configuration has two responsibilities:

- Environment settings hold deployment-specific values and secrets: database URL, storage root or endpoint, model ID, Modal app/function names, and policy-file path.
- `config/policy.yaml` is the source of operational limits: file/page limits, global and per-job budgets, confirmation threshold, hard stop, cache fields, and Modal scaling limits.

Typed loaders validate both sources at startup. Budget values will be removed from `.env.example` unless they are explicitly supported overrides. Tests will prove invalid or contradictory policy values fail fast.

## Domain and validation

Domain models move out of the API package so transport, inference, and validation all depend on the same core contract.

- A borehole may have no collar.
- Easting and northing are either both present or both absent.
- Elevation may be present independently when explicitly reported.
- CRS metadata is preserved exactly and validated separately; the system does not guess a CRS.
- Evidence bounding boxes contain exactly four ordered values.
- Borehole intervals require at least one evidence record.
- Depth, confidence, RQD, and UCS bounds remain deterministic Pydantic checks.
- Cross-record checks return a validation report with errors and warnings. Persisting or returning an accepted extraction is prohibited when errors exist.
- Model ID, model revision when known, prompt version, and preprocessing version travel with inference results and cache records.

## Upload and storage

The upload endpoint will stream fixed-size chunks instead of reading the entire file into memory. While streaming, it will:

1. enforce the configured byte limit;
2. calculate SHA-256;
3. write to a temporary file beneath the configured storage root;
4. atomically finalize the file under a server-generated identifier;
5. return document ID, sanitized original filename, hash, size, and `UPLOADED` state.

Only PDF and DOCX inputs are accepted at this boundary. Parser-level validation follows in the inventory phase. Temporary files are removed on rejection or interrupted writes. User filenames never determine filesystem paths.

`DocumentStore` is an interface. `LocalDocumentStore` is the Phase 0 implementation; S3-compatible storage can replace it without changing API or domain code.

## Inference providers and Modal

`InferenceProvider` defines a small batch extraction contract.

- `MockInferenceProvider` returns deterministic fixture responses for local development and CI.
- `ModalInferenceProvider` lazily imports the official Modal SDK and invokes the named deployed function. If Modal is unavailable or unconfigured, it returns a clear configuration error rather than silently using another provider.
- Provider selection is explicit configuration. Production does not fall back from Modal to mock inference.

`deployment/modal_worker.py` remains the serverless GPU application. It will preserve:

- L4 GPU selection;
- zero minimum containers;
- one maximum container;
- short scale-down window;
- bounded timeout and no automatic paid retries;
- Qwen3.6-27B-NVFP4 served through vLLM.

The worker starts vLLM once per warm container lifecycle, waits for readiness, consumes or redirects process output so logs cannot fill an unread pipe, validates request shape, and returns per-item structured failures rather than aborting an entire batch on one malformed response. Exact Modal lifecycle APIs and dependency versions will be checked against current official documentation during implementation.

No test or smoke command will invoke a paid GPU function. A real deployment or benchmark is a separately reported operator action.

## Budget and cache controls

The budget service separates estimation, authorization, reservation, and recording.

- Authorization checks the job cap, global hard stop, and remaining unreserved budget.
- A successful authorization reserves funds so concurrent requests cannot authorize the same balance.
- Completion records actual usage and releases the unused reservation.
- Failure or cancellation releases the reservation.
- The in-memory repository is deterministic and locked for tests/local mode. The interface allows a transactional database implementation when the job controller is added.

The cache key includes document hash, figure hash, model ID, model revision when known, prompt version, and preprocessing version. Policy and code will list the same fields.

## Database boundary

Alembic becomes the authoritative migration mechanism. The baseline schema will include projects, documents, boreholes, intervals, evidence, evidence links, inference jobs, usage records, and cache records required by the stabilized contracts.

Native easting, northing, elevation, and CRS remain authoritative and nullable. A PostGIS point uses the row's known SRID and is not falsely declared as EPSG:4326. Browser-friendly WGS84 coordinates are derived only after a known transform. Evidence links maintain explicit relationships to boreholes and intervals instead of leaving evidence orphaned.

`database/schema.sql` will either be regenerated as a clearly marked snapshot or removed from the authoritative path so it cannot drift from migrations.

## API behavior and errors

The API will use an application factory with injected settings, policy, storage, budget repository, and inference provider. Tests can create isolated applications without mutating a process-global ledger.

Existing endpoints remain, with these changes:

- `/health` reports service status and version without exposing secrets.
- `/budget` reports configured limits and current local repository state.
- `/documents/upload` returns a durable document receipt and never launches inference.

Errors use stable codes for invalid configuration, unsupported document type, oversized upload, storage failure, validation rejection, budget rejection, Modal unavailable, and inference failure. Document contents are excluded from exception logs.

## Testing strategy

Implementation follows red-green-refactor. Tests are written before each behavior change.

Required coverage includes:

- package build and imports;
- official Modal SDK resolution rather than a local `modal` package;
- configuration and policy validation;
- nullable collar coordinates and paired XY enforcement;
- mandatory interval evidence and cross-record validation;
- cost hard stop, reservations, release, and actual usage;
- cache-key version fields;
- streaming upload hashing, size rejection, path safety, persistence, and cleanup;
- deterministic mock provider behavior;
- API health, budget, and upload responses;
- Modal worker import/configuration smoke test without remote execution;
- migration metadata and schema invariants that can be checked without a GPU.

The completion gate is:

```text
python -m pytest -q
ruff check .
python -m build
python -c "from apps.api.app.main import app"
modal deploy deployment/modal_worker.py  # only with configured credentials; no function invocation
```

The first four commands must pass locally in a supported Python environment. The Modal deployment command is verified when credentials are available. Deployment does not invoke the GPU function, although ordinary Modal image-build, storage, or network charges may still apply.

## Migration sequence

1. Add failing tests for packaging, contracts, configuration, and the Modal collision.
2. Create the core package and move imports behind compatibility re-exports where useful.
3. Rename the local Modal deployment directory and repair worker lifecycle behavior.
4. Add typed configuration and align all policy consumers.
5. Add storage and streaming upload behavior.
6. Add provider interfaces and deterministic mock behavior.
7. Add migration infrastructure and repair the baseline data model.
8. Update documentation and run the complete verification gate.

## Acceptance criteria

- A supported Python environment can install the project and development dependencies reproducibly.
- All automated tests and static checks pass without GPU access.
- The FastAPI application starts with local storage and mock inference.
- Uploads are streamed, hashed, persisted, and returned with document IDs.
- Missing coordinates remain null and partial XY coordinates are rejected.
- Missing required provenance rejects an extraction.
- Budget authorization cannot oversubscribe the configured balance.
- The official Modal SDK imports successfully from the worker.
- The Modal deployment retains L4, scale-to-zero, and one-container limits.
- No local module named `modal` remains to shadow the SDK.
- A production configuration can select Modal explicitly; it never silently falls back to mock inference.

## Risks and controls

- GPU/model fit is unproven: deployment and paid benchmarking remain separate, explicit steps.
- Modal and vLLM APIs change: implementation checks current official documentation and pins tested versions.
- PostGIS is unavailable in lightweight CI: migration structure and SQL invariants run locally, while a PostGIS service test can run in integration CI.
- Broad refactoring could break imports: compatibility re-exports and focused tests keep migration incremental.
- Local upload storage is not production storage: the interface prevents coupling and documents that limitation.
