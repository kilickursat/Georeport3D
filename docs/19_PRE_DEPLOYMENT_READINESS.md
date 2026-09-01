# GeoReport3D Pre-Deployment Readiness Register

## Purpose and audit boundary

This document records what is real, intentionally fake, stale, or only scaffolded before any
deployment. It is an evidence register, not a claim that the MVP is complete.

The original audit covers the repository state on 2026-08-27: the root README, `docs/00` through
`docs/18`, the developer checklist, Python source, tests, configuration, Modal deployment code,
database SQL, and the web boundary. Source inspection and dependency-free checks can establish
code contracts, but they cannot prove a cloud image builds, a model fits, PostGIS migrations run,
or the browser workflow works.

The document-boundary rows and narrative were updated on 2026-08-31 after code-level repair of
local storage suffixes, Docling normalization, deterministic classification, and inventory
pagination truth. That update is not target-environment or deployment evidence.

No Modal deployment, model download, model load, vLLM launch, GPU allocation, paid inference,
FastAPI Cloud action, Docker pull, or remote CI run was attempted during this work. Model weights
must not be downloaded to the local workstation. Modal and model investigation is intentionally
deferred until the user runs the deployment and returns concrete logs or failures.

The manual GitHub Actions boundary uses protected GitHub environment `modal-production`. Its
GitHub secrets are exactly `MODAL_ID` and `MODAL_ID_SECRET`, mapped only at runtime to
`MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`. It rejects refs other than `refs/heads/main` and targets
Modal environment `main` explicitly. Modal named Secret and Volume lookups are environment-scoped,
so `huggingface-secret`, `georeport3d-hf-cache`, and `georeport3d-vllm-cache` refer to resources in
that `main` environment.

No live Modal verification was performed for the workflow hardening. Source contracts cannot
prove credentials, Modal SDK behavior, an image build, model access, GPU fit, inference, cost, or
scale-to-zero; those remain separately authorized target-environment gates.

An unchecked item in `docs/15_DEVELOPER_CHECKLIST.md` means **not yet proven in the required
environment**. It is not automatically a test failure. A failed gate requires an attempted check
and recorded failing evidence; a deferred gate has not been attempted because its environment or
authorization is unavailable.

## Status vocabulary

### FAKE

An intentional substitute for real infrastructure, data, or behavior. Examples are a deterministic
mock provider, fake Modal remote objects, and synthetic extraction examples. A fake is useful when
it is clearly identified and constrained to tests or development. It becomes dangerous if
production can select it silently, if synthetic output is presented as measured geology, or if a
test double is mistaken for deployment evidence.

### STALE

An artifact that contradicts the current architecture, contains obsolete generated state, or has
drifted from the authoritative source. Stale artifacts must be replaced, regenerated, or excluded;
they must not be treated as an alternative source of truth.

### SCAFFOLD / NOT YET WIRED

Code, configuration, documentation, or contracts that define the intended boundary but do not yet
provide the complete user-facing path. Scaffold code may be well tested in isolation while still
lacking persistence, orchestration, UI, external-service verification, or target-environment proof.

### DEPLOYMENT-READY

A real implementation that is integrated into its consuming workflow, has locked dependencies,
has no unresolved stale state, has appropriate security and observability, and has passed both
code-level and target-environment gates with retained evidence. A source file is not
deployment-ready merely because it compiles or has unit tests.

## Overall assessment

The repository is suitable for continued code-level development and offline contract review. It is
currently a **NO-GO for public or paid deployment**. The upload foundation, domain contracts,
budget ledger, cache-key function, storage implementation, Modal worker contract, CPU-side
provider, PostGIS metadata/baseline migration, and CPU document adapter/inventory are real code.
The document pipeline is not wired to its API workflow or proven with the optional backend in this
environment. Job orchestration, persistent cache and budget accounting, persistence integration,
web application, authentication, production observability, dependency lock, and target-environment
verification are not complete. The PostGIS code has not been executed against a database.

No concrete item below is classified as fully `DEPLOYMENT-READY` yet because the repository does
not currently satisfy the integration, security, reproducibility, and environment-proof parts of
that definition.

## Concrete item register

| ID | File or path | Class | Current behavior or evidence | Remain? | Required pre-deploy state or action | Evidence required | Risk if deployed unchanged |
|---|---|---|---|---|---|---|---|
| F-01 | `georeport3d/inference/mock.py` | FAKE | Returns deterministic deep copies; performs no inference. | Yes, tests/dev only. | Keep selectable only outside production; keep the production guard and add an environment-startup assertion. | Production startup fails with `APP_ENV=production` plus `INFERENCE_PROVIDER=mock`; tests prove no fallback. | Synthetic extraction could be presented as real. |
| F-02 | `apps/api/app/dependencies.py` mock response | FAKE | Empty extraction fixture with `document_id=mock`. | Yes, tests/dev only. | Label responses as mock in development UI/log metadata; never persist them as observed geology. | Mock-mode end-to-end test and production rejection test. | Empty fake output could mask missing inference wiring. |
| F-03 | `tests/inference/test_modal_provider.py` fake remote objects | FAKE | Emulate `.remote()` and malformed envelopes without Modal. | Yes, tests only. | Keep isolated under `tests`; supplement, never replace, deployment smoke evidence. | Local tests pass plus later real Modal result-envelope smoke. | False confidence that network, credentials, image, or GPU work. |
| F-04 | `tests/modal/test_worker.py` AST/helper fakes | FAKE | Exercises pure helpers and source declarations without importing the Modal SDK. | Yes, tests only. | Keep as fast contract tests; run official SDK import and image build separately. | Unit/source tests plus target Modal build evidence. | Pinned declarations may be incompatible with the real platform. |
| F-05 | `examples/borehole_extraction.json` | FAKE / PLACEHOLDER | Synthetic BH-07 data uses placeholder `EPSG:0000`. | Yes, only if labeled synthetic. | Add an explicit synthetic-data label and prevent ingestion as accepted production evidence. | Example-schema test; UI identifies it as demo data. | Placeholder coordinates/CRS could be mistaken for field evidence. |
| S-01 | `database/schema.sql` | STALE SNAPSHOT RETIRED | The false `PointZ, 4326` scaffold was removed and replaced by a non-executable warning; it is not generated SQL. | Keep the warning only until generation. | Generate a labeled reference from Alembic revision `20260827_0001`; migrations remain authoritative. | Offline SQL comparison, successful `alembic upgrade head`, and PostGIS queries. | Treating the warning as a schema would fail; no reviewed generated snapshot exists yet. |
| S-02 | `migrations/versions/20260827_0001_baseline.py` | SCAFFOLD / CODE-LEVEL | Explicitly defines observation/evidence links, jobs, usage, cache, native coordinate checks, and mixed-SRID geometry. | Yes. | Run metadata parity and a clean upgrade against approved PostGIS; generate the reference SQL. | Dependency-backed metadata checks, migration head, table/FK/constraint/index inspection. | Source/runtime drift or unsupported PostGIS behavior may remain hidden. |
| S-03 | `**/__pycache__/` and `*.pyc` | STALE / GENERATED | Local bytecode exists for multiple Python versions; one observed API bytecode artifact contains older `0.1.0` behavior. | No. | Exclude from source control and delete/regenerate locally as needed. | Clean staged-file inventory contains none; imports compile from source. | Reviewers or packaging steps may inspect obsolete behavior. |
| S-04 | `build/`, `dist/`, `georeport3d.egg-info/` | STALE / GENERATED | Build outputs exist but the dependency-backed isolated build gate is deferred. | No, not as source. | Remove from the commit; regenerate only after locked, successful build verification. | Fresh build hashes/artifact inspection from the release commit. | Old packages may not match reviewed source or dependencies. |
| C-01 | `deployment/modal_worker.py` | SCAFFOLD / CODE-LEVEL | Declares Modal app, L4, scale-to-zero, one-container cap, pinned image packages, volumes, one vLLM subprocess, readiness polling, and strict result envelopes. | Yes. | Validate against the installed Modal SDK, build the image, load the model on Modal, and test lifecycle/error paths. | SDK import, Modal build logs, readiness logs, one authorized smoke result, shutdown/scaling evidence. | Import/API drift, image-build failure, OOM, startup timeout, or malformed model output. |
| C-02 | `deployment/modal_worker.py` MTP setting | SCAFFOLD / EXPERIMENTAL | Requests two speculative MTP tokens and avoids Marlin by source contract. | Yes, pending benchmark. | Treat MTP as a benchmark candidate; retain only if correctness, memory, and latency evidence supports it. | Controlled Modal benchmark with and without MTP. | Startup incompatibility or worse cost/performance. |
| C-03 | `georeport3d/inference/modal_provider.py` | SCAFFOLD / CODE-LEVEL | Lazily resolves `modal.Cls`, calls one remote method, validates cardinality/envelopes, and emits generic non-leaking failures. | Yes. | Invoke it only through an explicit job controller after cache and budget authorization; verify with the deployed class. | Fake-boundary tests plus one authorized real RPC trace with redacted logs. | Direct calls could bypass cost governance; SDK/deployment name drift may fail at runtime. |
| C-04 | `tests/modal/test_namespace.py` | SCAFFOLD / DEFERRED GATE | Proves the repository no longer shadows the official `modal` package, but requires the SDK. | Yes. | Run after approved dependency sync. | Test passes and `modal.__file__` resolves outside the repository. | Local namespace collision could break deployment tooling. |
| C-05 | `deployment/README.md` | SCAFFOLD / CODE-LEVEL RUNBOOK | Records intended commands, rollback, logs, volumes, external secrets, cost boundaries, separate smoke authorization, and evidence collection; none were executed here. | Yes. | Validate every command against the approved Modal SDK and environment, then revise the runbook from retained operator evidence. | Runbook review plus a user-executed build/deployment later. | SDK drift or an untested operator assumption could make the procedure fail. |
| C-06 | `georeport3d/config.py`, `config/policy.yaml` | SCAFFOLD / CODE-LEVEL | Typed policy constrains L4 and scaling; production rejects mock; limits and canonical cache fields are modeled. | Yes. | Validate every production setting at startup and version policy changes; connect limits to every relevant workflow. | Config tests and staging startup with production-shaped non-secret config. | Declared policy may not be enforced by orchestration. |
| C-07 | `apps/api/app/main.py` health and budget routes | SCAFFOLD / CODE-LEVEL | `/health` is shallow; `/budget` reports one in-memory ledger. | Yes. | Add readiness/dependency health and persistent, scoped budget accounting. | API tests, restart test, concurrent reservation test, dependency-failure probes. | Healthy response may hide failed DB/provider; restart loses spend. |
| C-08 | `apps/api/app/main.py` upload route | SCAFFOLD / CODE-LEVEL | Streams PDF/DOCX by suffix, enforces byte limit, hashes and stores with a canonical lower-case source suffix, and does not invoke inference. Upload is still not wired to inventory. | Yes. | Add content/type validation, malware/content policy as required, metadata persistence, ownership, retention, retrieval controls, and explicit inventory orchestration. | API tests with real fixtures, hostile files, restart, permissions, cleanup, and upload-to-inventory flow. | Untrusted or mislabeled content may be stored; orphaned uploads may accumulate; users cannot request inventory. |
| C-09 | `georeport3d/storage/local.py` | SCAFFOLD / CODE-LEVEL | Uses bounded streaming, sanitized display names, SHA-256, fsync, no-clobber publication, and durable `<id>.pdf`/`<id>.docx` lookup under a resolved root. Restart lookup uses the filesystem, rejects ambiguous/non-regular entries, and surfaces legacy `<id>.bin` as unknown format. | Yes for local/dev. | Select a durable private production store, define backup/retention/encryption, persist receipts transactionally, and verify/re-upload or explicitly migrate legacy BIN entries without guessing their type. | Fault-injection, cross-format collision, restart, legacy-state, production-store integration, and recovery tests. | Single-host loss, missing lifecycle policy, or inaccessible/ambiguous legacy files after scaling. |
| C-10 | `georeport3d/services/budget.py` | SCAFFOLD / CODE-LEVEL | Thread-safe in-memory estimates, reservations, release, and record operations. | Yes as domain logic. | Back it with transactional persistence and idempotent job state; calibrate the rate/estimator from real runs. | Concurrency/restart tests and reconciliation against Modal usage. | Restart or multiple API replicas can overspend the cap. |
| C-11 | `georeport3d/services/cache.py` | SCAFFOLD / CODE-LEVEL | Produces a canonical versioned SHA-256 key only. | Yes. | Implement a persistent cache store, lookup-before-budget/GPU ordering, validated result storage, and invalidation policy. | Cache miss/hit integration test proving the second request makes no remote call. | Duplicate GPU spend or reuse of mismatched results. |
| C-12 | API inference provider on `app.state` | SCAFFOLD / NOT WIRED | Factory builds/injects a provider, but no route invokes it. | Yes. | Add explicit estimate/analyze job orchestration; upload must remain inference-free. | End-to-end mock job test and later authorized Modal job test. | A deploy appears functional while analysis is unavailable. |
| C-13 | `docs/10_API_AND_JOB_STATE.md` endpoints/state machine | SCAFFOLD / DOCS ONLY | Specifies inventory, estimate, analyze, status, cancel, extraction, borehole, section, and page endpoints; code implements only health, budget, upload. | Yes as target spec. | Implement states, idempotency, cancellation, timeout, persistence, and error transitions. | Contract/integration tests covering every state and duplicate request. | Missing workflow, duplicate jobs, uncontrolled cost, and inconsistent status. |
| C-14 | `georeport3d/domain/models.py` and validation | SCAFFOLD / CODE-LEVEL | Enforces evidence for boreholes/intervals, paired XY, bounds, and interval-vs-total-depth checks. | Yes. | Expand deterministic CRS, duplicate, overlap, provenance completeness, unit, and cross-record validation. | Property/fixture tests and rejection corpus. | Invalid or contradictory geology may be accepted. |
| C-15 | `ai/prompts/` | SCAFFOLD / NOT WIRED | Prompt constants prohibit invention and request provenance, but are not connected to a versioned task builder. | Yes. | Add prompt assembly, image/text boundaries, schemas, version IDs, token limits, and injection tests. | Golden prompt tests and extraction benchmark provenance. | Worker may receive inconsistent or unsafe prompts. |
| C-16 | `document/` | SCAFFOLD / CODE-LEVEL | Lazily adapts Docling PDF/DOCX output into deterministic pages/regions, normalizes finite top-left boxes, preserves mixed unplaced content on marked synthetic pages, classifies strongest evidence with deterministic specificity ties, and enforces a default 500-page normalized-result limit. Backend/factory/normalization failures are detached and generic. | Yes, continue and wire. | Wire upload/storage to inventory without invoking GPU; add a durable pagination-truth field to Evidence via Alembic before synthetic page evidence can persist; choose a stable pre-conversion limit if backend work must be bounded; benchmark real reports/OCR needs. | Dependency-free adapter regressions plus GitHub Actions with Pydantic/Docling PDF and DOCX fixtures, max-page, failure-sanitization, inventory, and upload-to-parser tests. | The post-conversion guard does not cap Docling CPU/memory work; synthetic evidence cannot yet persist; OCR is off; real-report completeness is unproven. |
| C-17 | `geology/` | SCAFFOLD / EMPTY | No coordinate transformation, borehole geometry, sections, or uncertainty engine exists. | Yes, implement incrementally. | Start with observed boreholes and deterministic CRS transforms; do not interpolate unsupported geology. | Known-coordinate transformation fixtures and visual spatial checks. | Wrong placement or invented surfaces. |
| C-18 | PostGIS ORM/migrations/repositories | SCAFFOLD / CODE-LEVEL | SQLAlchemy metadata and an explicit Alembic baseline now exist; repositories and live database proof do not. | Yes. | Verify the migration, then add repositories and transaction boundaries. | Metadata/runtime tests, migration head, real PostGIS upgrade, CRUD/provenance tests. | Schema/runtime drift and no application-level durable observations/jobs/costs. |
| C-19 | `apps/web/README.md` | SCAFFOLD / DOCS ONLY | Declares Next.js, React, CesiumJS, React Three Fiber and viewer layers; no web source/package manifest exists. | Yes as architecture. | Implement upload/job/evidence UI and an initial lightweight borehole viewer. | Browser tests and known-coordinate screenshots/interaction recordings. | There is no usable browser product. |
| C-20 | CesiumJS plus Three.js design | SCAFFOLD / PRESERVE | CesiumJS owns geospatial context; Three.js/R3F owns engineering geometry and interaction. | Yes. | Keep both roles explicit and feed them stable API coordinates/provenance. | Coordinate fixtures and visual acceptance tests. | Role drift can duplicate transforms or create inconsistent scenes. |
| C-21 | 3D Tiles | SCAFFOLD / FUTURE | Architecture reserves 3D Tiles for large streamed datasets; first MVP does not require it. | Yes as future design, not a current gate. | Begin with JSON/GeoJSON/lightweight Three.js; add tiles only after measured scale need. | Dataset/performance benchmark justifying tiling. | Premature tiling increases complexity; claiming support now misleads users. |
| C-22 | Authentication/authorization | SCAFFOLD / NOT PRESENT | Security doc lists later controls; routes currently have no user, project ownership, or role checks. | No public deployment without it. | Implement authentication, project authorization, job/file ownership, and administrative separation. | Security integration tests and access-control review. | Unauthorized access to confidential reports and GPU spending. |
| C-23 | Rate limits/CORS/CSRF/signed URLs | SCAFFOLD / NOT PRESENT | Requirements are documented but not implemented. | Required before internet exposure. | Define trusted origins, request/rate limits, upload/download controls, and private signed access. | Staging security tests and configuration review. | Abuse, cross-origin exposure, data leakage, and budget exhaustion. |
| C-24 | `.env.example` and `.gitignore` | SCAFFOLD / CODE-LEVEL | Secret fields are placeholders; `.env*` is ignored except the example; generated/local data paths are ignored. | Yes. | Use a secrets manager or platform secrets; scan the staged tree and history before push/deploy. | Secret scan reports zero credentials; staging reads secrets externally. | Credential exposure or insecure default reuse. |
| C-25 | `pyproject.toml` | SCAFFOLD / CODE-LEVEL | Defines supported Python and bounded dependency ranges, but not a resolved environment. | Yes. | Include all real runtime/migration dependencies and generate a reviewed lock in an approved environment. | Successful locked sync on Python 3.12/3.13 and dependency audit. | Non-reproducible or incompatible builds. |
| C-26 | `uv.lock` | SCAFFOLD / ABSENT | No lock file exists because dependency resolution was blocked by the firewall. | Must be created. | Generate with approved network access; review source and resolved versions. | Clean `uv sync --frozen` succeeds. | Dependency drift and unverifiable release contents. |
| C-27 | `tests/` and Ruff/build gates | SCAFFOLD / PARTIALLY CHECKABLE | Focused tests exist, including a dependency-free upload/storage-to-fake-Docling boundary unittest, but full pytest, Pydantic inventory tests, optional real Docling tests, Ruff, build, and FastAPI import gates are deferred without dependencies. | Yes. | Run the exact documented gates in GitHub Actions/after approved sync; add integration/e2e/security tests for missing workflows. | Retained command output from the release commit; no unexpected skips. | Source-only and fake-converter confidence may hide framework/backend integration failures. |
| C-28 | Observability | SCAFFOLD / NOT PRESENT | No structured application logging, metrics, traces, audit log, durable job events, or alert rules are implemented. | Required before production. | Add redacted structured logs, request/job IDs, state/cost metrics, provider latency/errors, and alerts. | Staging trace of one job plus redaction and alert tests. | Failures/cost spikes become invisible; confidential content may leak during ad hoc debugging. |
| C-29 | vLLM/Modal output handling | SCAFFOLD / UNVERIFIED | Worker inherits child stdout to avoid pipe deadlock; request-content redaction has not been proven against real vLLM logs. | Yes with controls. | Verify logging flags and retained logs contain no prompts, images, raw pages, model output, or tokens/secrets. | Redaction inspection from authorized smoke/build logs. | Confidential report content may enter provider logs. |
| C-30 | `.venv/` and `.superpowers/` | GENERATED / LOCAL | Local environment and implementation evidence are intentionally ignored. | Local only. | Never stage; recreate environment from the lock. Retain internal evidence locally as needed. | Staged-file inventory excludes both. | Huge, machine-specific, or sensitive files enter the release. |

## Modal: code-only state and later investigation

The intended production inference path remains **Modal serverless GPU**, not a local model and not
the deterministic mock. `deployment/modal_worker.py` contains a plausible deployment definition
for one L4 container with `min_containers=0`, `max_containers=1`, `buffer_containers=0`, a short
scale-down window, no retries, persistent cache volumes, and one vLLM child per warm container.
`georeport3d/inference/modal_provider.py` is a CPU-side adapter that imports the SDK lazily and does
not silently fall back to mock.

Those facts are code evidence only. They do not prove that Modal accepts every declaration, that
the CUDA/vLLM/image dependency combination builds, that the checkpoint is accessible, that it fits
an L4, that multimodal requests work, that MTP is beneficial, or that scale-to-zero behaves as
expected. The AST tests and fake remote tests are deliberately fake with respect to cloud behavior.

Before deployment, the API must also place `cache lookup -> workload/cost estimate -> budget
reservation -> explicit user authorization -> Modal call -> validation -> persistence -> usage
record` in one controlled job flow. The current upload route does not and must not invoke Modal.

The next Modal investigation should start only after a user-run build or deployment produces real
evidence. Useful evidence includes the exact command, Modal SDK version, image-build error, class
registration output, vLLM startup log, readiness result, GPU memory/timeout data, generic failure
envelope, scale-down observation, and redaction review. Do not send model weights, prompts, report
content, or credentials back as debugging evidence.

## Database and PostGIS

The former `database/schema.sql` content falsely labeled arbitrary native easting/northing as
WGS84. It has been retired as a non-executable warning, not represented as generated SQL.
`ST_SetSRID` could not repair that error because it labels coordinates rather than transforms
them. Native coordinates and original CRS remain authoritative and nullable in the code-level
metadata; geometry requires a coordinate pair and a positive matching SRID.

The target database layer needs projects, documents, boreholes, intervals, evidence and explicit
evidence links, inference jobs, usage records, and cache entries. Constraints must cover paired XY,
depth ordering, confidence/RQD ranges, uniqueness, and foreign keys. Alembic must be authoritative;
the SQL file is only a generated, labeled review snapshot. Even after metadata and migrations exist,
actual application repositories and transactional job/persistence wiring remain separate gates.

A real PostGIS check is a user/environment gate. Do not treat metadata inspection or offline SQL
generation as proof that the extension, geometry indexes, upgrade, downgrade, or spatial queries
work on PostgreSQL/PostGIS.

## API, job, budget, cache, and storage wiring

The implemented API surface is currently `GET /health`, `GET /budget`, and
`POST /documents/upload`. Upload performs bounded storage and hashing and correctly avoids
inference. The documented vertical slice still needs inventory, estimate, analyze, job status,
cancel, extraction, borehole, section, and source-page routes.

The budget ledger and cache key are meaningful reusable domain components, not fake behavior. They
are nevertheless scaffolded at system level: budget state is in process memory, and there is no
cache store. A production job controller must make cache lookup and durable budget reservation
atomic/idempotent enough that retries, multiple API replicas, restarts, or repeated browser requests
cannot create duplicate GPU spend.

The local filesystem store is appropriate for development and code-level tests. New durable names
retain the validated canonical `.pdf` or `.docx` suffix, and `path_for(document_id)` discovers that
format from disk after restart rather than relying on an in-memory index. The ID namespace covers
both canonical formats, legacy BIN entries, and temporary reservations; publication remains
no-clobber. A legacy `<document_id>.bin` has no durable trusted format metadata. Operators must
re-upload it or verify its type from trusted records/content validation and migrate it to exactly
one canonical name; automatic sniffing or filename guessing is intentionally absent.

Production must choose and verify a private durable store, persist receipt metadata, enforce
ownership and retention, and define recovery. File suffix acceptance alone is insufficient
validation for hostile or mislabeled uploads.

## Document boundary: code-only state and limitations

`DoclingDocumentParser` accepts an explicit `max_pages` argument with a default of 500. The check
runs only after conversion and normalization. It prevents an over-limit result from entering the
inventory/inference path, but it does **not** bound Docling's CPU, memory, or time while converting
the source. A stronger resource boundary requires a supported backend preflight/page-limit API or
an independently validated pre-conversion counter; neither is claimed here.

Normalization retains unplaced text, pictures, and tables instead of silently dropping them. It
appends them in backend order to a deterministic synthetic page after any placed pages. DOCX page
ordinals are also synthetic because the source is a flow format. Pagination truth is carried per
parsed/inventory page, so a real PDF page in a mixed document remains distinguishable from the
synthetic overflow page. The current durable `Evidence` model cannot carry that truth. Therefore
`DocumentInventory.evidence_for` permits real pages and rejects synthetic pages rather than
persisting a false printed-page citation. The precise follow-up is an Alembic migration plus ORM,
Pydantic, repository, and API mapping for a field such as `page_number_is_synthetic` (or an
equivalent pagination-kind enum); only then should synthetic-page evidence be persisted.

All factory, conversion, and normalization failures crossing the Docling boundary are replaced by
generic exception objects with no original cause or context. Optional malformed bounding boxes
are dropped by the adapter, while normalized/inventory/evidence contracts reject any NaN or
infinite coordinate. OCR remains disabled and completeness on scanned or mixed real reports is a
separate benchmark gate.

## Web mapping and 3D rendering

The stack decision remains unchanged:

- CesiumJS provides terrain, globe/project context, GIS overlays, and future large tiled datasets.
- Three.js through React Three Fiber provides borehole cylinders, sections, clipping, measurement,
  annotations, and engineering interactions.
- 3D Tiles remains a future streaming format when measured dataset scale justifies it. It is not a
  first-MVP acceptance requirement.

At present, `apps/web/README.md` is a boundary document, not an application. There is no frontend
package manifest or UI source. The first viewer should consume versioned API JSON/GeoJSON and
render observed boreholes in verified coordinates. It must expose evidence and visibly distinguish
observed, inferred, hypothesis, and unknown information. Cesium and Three.js must share one tested
display-coordinate pipeline rather than independently transforming the same native coordinates.

## Security, secrets, and authentication

Positive code-level controls include production rejection of the mock provider, ignored `.env`
files, placeholder-only secret fields in `.env.example`, sanitized upload display names, generic
upload/provider errors, and no inference on upload. These are foundations, not complete production
security.

Before any internet-facing deployment, add authentication, project/file/job ownership checks,
authorization, rate limiting, explicit CORS/CSRF policy, private/signed file access, audit events,
retention/deletion policy, and secret-manager integration. Establish upload content validation and
the required malware scanning/quarantine policy for confidential reports. Prompt construction must
keep system instructions separate from untrusted document content.

Run a staged-tree and history secret scan before push and before deployment. Never commit Modal
tokens, database production credentials, object-storage keys, reports, page images, prompts, raw
model output, or provider logs containing user content.

## Dependencies, lock, tests, and build

`pyproject.toml` provides bounded ranges and supports Python 3.12/3.13, but `uv.lock` is absent and
the workspace could not complete dependency synchronization through the company firewall. The
full pytest, Ruff, isolated build, and FastAPI import gates are therefore deferred, not passing and
not failing. Do not bypass the firewall or use remote CI as a substitute.

After sync in an approved environment, use the lock as the source of exact versions and run all
documented gates from a clean checkout. Review skips and warnings. Normal CI must remain GPU-free;
Modal worker tests should use pure helpers/fakes, and database integration tests should be opt-in
with an explicit test URL. A separate authorized deployment smoke supplies cloud proof.

The web stack has no dependency manifest yet, so JavaScript dependency locking, type checks,
linting, unit tests, production build, browser tests, and asset/license checks are all future gates.

## Observability and operations

`/health` proves only that the API process can answer a simple request. Production needs separate
liveness and readiness semantics for storage, database, policy/config, and any job queue. Add
structured, redacted logs with request, document, project, and job correlation IDs; job-state event
history; cache hit/miss metrics; budget reservation/spend metrics; Modal latency/startup/error
metrics; storage errors; and alerts for cost, job failures, timeouts, and unavailable dependencies.

Logging must be tested with realistic confidential-shaped fixtures. Logs must not contain uploaded
bytes, page images, full prompts, raw output, excerpts, credentials, or signed URLs. Confirm real
vLLM and Modal logging behavior during the later user-authorized smoke rather than assuming source
code controls provider-generated output.

Document rollback and recovery for the API, migration, object store, and Modal deployment. Retain
release version, model/revision, prompt/preprocess versions, policy version, migration head, and
frontend build identity with every deploy.

## Generated and non-authoritative artifacts

Generated bytecode, caches, local environments, build outputs, coverage output, uploads, frontend
builds, and internal SDD evidence must remain excluded by `.gitignore`. In particular, Python
bytecode from multiple interpreters is not evidence that the current source works; observed stale
bytecode contains behavior older than the source version.

`database/schema.sql` is a special case: once corrected, it may remain as a generated review
snapshot, but it must state its Alembic revision and non-authoritative status. Until that generation
occurs, the current EPSG:4326 version is stale and must not ship as deployment guidance.

Before commit/release, inspect the exact staged file list. Generated artifacts, `.env`, credentials,
uploaded documents, model/cache files, database volumes/dumps, provider logs, and internal
`.superpowers` evidence must not be staged.

## Ordered pre-deployment gates

### A. Code-level gates

These gates require code and local dependencies but do not require a model, GPU, paid cloud call,
or production credentials.

1. Review and execute the code-level SQLAlchemy/Alembic baseline; generate `database/schema.sql`
   from that migration and label it non-authoritative.
2. Implement PostGIS repositories and transactions for documents, observations, evidence links,
   inference jobs, usage, and cache records.
3. Wire the code-level CPU PDF/DOCX inventory into the upload/job workflow; run the Pydantic and
   optional Docling fixture suites in GitHub Actions, add the synthetic-pagination Evidence schema
   migration, and retain deterministic real-report inspection evidence.
4. Implement the persistent cache and durable budget/job controller in the enforced order:
   cache -> estimate -> reserve/confirm -> inference -> validate -> persist/reconcile.
5. Implement missing job, extraction, spatial, and source-page endpoints with idempotency,
   cancellation, timeouts, ownership hooks, and stable error codes.
6. Expand deterministic validation for CRS, units, duplicates, overlaps, evidence completeness, and
   cross-record consistency; accepted unsupported coordinates must remain impossible.
7. Implement the Next.js/React viewer using CesiumJS for geospatial context and Three.js/R3F for
   engineering rendering; keep 3D Tiles deferred until a scale benchmark justifies it.
8. Add authentication/authorization integration points, safe upload handling, explicit CORS/CSRF
   and rate-limit configuration, secret loading, retention, and private file access.
9. Add redacted structured logging, metrics, traces/job events, readiness checks, alerts, and
   rollback/recovery documentation.
10. Generate and review `uv.lock`; add and lock the web manifest; run dependency/license/security
    audits appropriate to the deployment policy.
11. From a clean checkout on supported Python, run `uv sync --frozen`, full pytest, Ruff, isolated
    package build, API import, database metadata/offline migration checks, frontend type/lint/unit
    tests, and frontend production build. Record exact outputs and unexpected skips.
12. Run GPU-free end-to-end tests with the mock provider, proving upload alone never invokes
    inference and a cache hit prevents the fake remote boundary from being called.

### B. User and target-environment gates

These gates require the user's approved environment, credentials, services, data, or cost
authorization. They are intentionally not attempted here.

1. From a clean approved workstation, reproduce the locked Python and web builds without bypassing
   network policy; record platform and resolved versions.
2. Start an isolated non-production PostGIS instance, apply `alembic upgrade head`, inspect the
   migration head/tables/constraints/indexes, test native/project CRS transformations, and exercise
   repository CRUD plus restart/recovery. Use a disposable test database, not production data.
3. Run the FastAPI service in mock mode and exercise health/readiness, upload, inventory, estimate,
   analyze, job status/cancel, extraction, evidence, and spatial endpoints across a restart.
4. Configure staging secrets externally and prove production startup rejects mock inference,
   missing secrets, unsafe origins, and unauthorized project/file/job access.
5. With fresh explicit authorization, run Modal setup/deploy from the reviewed release. A deploy
   may incur build/storage/network cost even before inference. Capture SDK version, build output,
   app/class identity, volumes, and rollback identifier. Do not download the model locally.
6. Only after checking the persistent budget and confirming a cache miss, separately authorize one
   paid, non-confidential smoke inference. Record model revision, GPU type, startup/readiness,
   latency, memory, timeout, result envelope, cost, and redaction evidence.
7. Compare MTP enabled/disabled; keep it only with correctness and cost/latency evidence. Confirm no
   automatic retry, one-container maximum, zero warm minimum, and observed scale-to-zero behavior.
8. Run the full vertical slice with a permitted real report: upload -> inventory -> explicit
   analysis -> validation -> provenance persistence -> PostGIS -> browser borehole/evidence view.
9. Run security tests for cross-user access, rate limiting, hostile/mislabeled uploads, prompt
   injection, secret/log leakage, signed/private file access, and deletion/retention behavior.
10. Build the annotated benchmark, publish extraction/safety metrics, and confirm accepted outputs
    contain zero hallucinated coordinates. Do not set final thresholds before baseline evidence.
11. Complete load, failure, cancellation, timeout, restart, backup/restore, rollback, monitoring,
    alert, and cost-reconciliation drills in staging.
12. Mark checklist items complete only from retained evidence for the target environment; record
    failures separately from checks that remain deferred.

## Go/no-go rule

Deployment is a **GO** only when every gate required for the intended exposure is complete, all
stale artifacts are replaced or excluded, fake paths are constrained to tests/development, and the
release has retained target-environment evidence. Until then, continue code-level work locally and
use user-run failures/logs to guide the next Modal or PostGIS investigation.
