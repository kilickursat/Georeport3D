# GeoReport3D Pre-Deployment Readiness Register

## Purpose and audit boundary

This document records what is real, intentionally fake, stale, or only scaffolded before any
deployment. It is an evidence register, not a claim that the MVP is complete.

The original audit covered the repository state on 2026-08-27. This register was reconciled with
the source again on 2026-09-08 after the persistent controller/API work and the code-level cloud
document-harness repair. The document-specific evidence ledger is
[`20_DOCUMENT_EXTRACTION_BENCHMARK_READINESS.md`](20_DOCUMENT_EXTRACTION_BENCHMARK_READINESS.md).
Source inspection and dependency-free checks can establish code contracts, but they cannot prove a
cloud image builds, a model fits, extraction is accurate, or the browser workflow works.

The document boundary was previously repaired for local-storage suffixes, Docling normalization,
deterministic classification, sparse-page OCR recovery, and inventory pagination truth. On
2026-09-08 the old substring benchmark was retired, current-tree report/raw-result artifacts were
removed, the production request gained a schema contract, and the cloud evaluation boundary was
hardened in source. None of those changes is extraction-accuracy or deployment evidence.

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

No live Modal verification was performed for the workflow hardening. The L40S worker changes,
structured output, Qwen non-thinking mode, evaluation Volumes, and manual workflow are code-level
only. Source contracts cannot prove credentials, Modal SDK behavior, an image build, model access,
GPU fit, inference, cost, extraction quality, or scale-to-zero; those remain separately authorized
target-environment gates.

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

### CODE-LEVEL / NOT YET WIRED

Code, configuration, documentation, or contracts that define the intended boundary but do not yet
provide the complete user-facing path or target-environment proof. Code may be well tested in
isolation while still lacking API orchestration, UI, external-service verification, or measured
quality. `PROVISIONAL` and `BLOCKED / DEFERRED` are used in the document-specific register for real
but insufficient evidence and deliberately unattempted gates.

### DEPLOYMENT-READY

A real implementation that is integrated into its consuming workflow, has locked dependencies,
has no unresolved stale state, has appropriate security and observability, and has passed both
code-level and target-environment gates with retained evidence. A source file is not
deployment-ready merely because it compiles or has unit tests.

## Overall assessment

The repository is suitable for continued code-level development and contract review. It is
currently a **NO-GO for public or paid deployment**. Upload, inventory, estimate, job-status,
domain contracts, a durable PostgreSQL-backed controller/budget/cache path, local development
storage, Modal provider/worker contracts, PostGIS metadata/migration, and the CPU document adapter
are real code. Locked GitHub CI includes PostGIS migration execution and has passed on the merged
baseline, but this unmerged branch has not supplied new remote CI or cloud-runtime evidence. The
`/analyze` vertical path, prompt/render assembly, field-gold extraction benchmark, canonical
Docling JSON preservation, production shared storage, web application, authentication,
authorization, and production observability remain incomplete.

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
| C-01 | `deployment/modal_worker.py` | CODE-LEVEL / UNVERIFIED | Declares an L40S Modal class with zero warm containers, a two-container cap, pinned image packages, persistent model caches, one vLLM subprocess, readiness polling, bounded batches/messages/images/schema, JSON-schema structured output, and Qwen thinking disabled. Startup flags now match the measured probe for CUDA library path, memory utilization, 32,768 context, 16 sequences, and one image per prompt. | Yes. | Validate against the approved Modal SDK, build the exact image, load the pinned model on L40S, and test schema compatibility, lifecycle, redaction, cost, and error paths. | SDK/image build logs, readiness/GPU memory data, one authorized structured-output smoke, log review, shutdown/scaling evidence. | Import/API drift, image-build failure, OOM, unsupported schema, startup timeout, or confidential output in logs. |
| C-02 | `deployment/modal_worker.py` former MTP setting | STALE / RETIRED | Speculative MTP was removed from the production command; it is no longer a current feature or readiness claim. | No in the production baseline. | Reintroduce only as a separately reviewed experiment after a controlled correctness, memory, latency, and cost benchmark. | Versioned A/B benchmark on the exact production model/image. | Stale documentation could imply an unmeasured optimization is active. |
| C-03 | `georeport3d/inference/modal_provider.py` | CODE-LEVEL / UNVERIFIED | Lazily resolves `modal.Cls`, forwards the server-generated response schema, calls one remote method, validates cardinality/envelopes, and emits generic non-leaking failures. `JobController` is the code-level governed caller, but no API route invokes the full path. | Yes. | Expose it only through authenticated `/analyze` job orchestration after cache and budget authorization; verify with the deployed class. | Unit boundary tests plus one authorized structured RPC trace with redacted logs. | An alternate direct caller could bypass cost governance; SDK/deployment/schema drift may fail at runtime. |
| C-04 | `tests/modal/test_namespace.py` | SCAFFOLD / DEFERRED GATE | Proves the repository no longer shadows the official `modal` package, but requires the SDK. | Yes. | Run after approved dependency sync. | Test passes and `modal.__file__` resolves outside the repository. | Local namespace collision could break deployment tooling. |
| C-05 | `deployment/README.md` | SCAFFOLD / CODE-LEVEL RUNBOOK | Records intended commands, rollback, logs, volumes, external secrets, cost boundaries, separate smoke authorization, and evidence collection; none were executed here. | Yes. | Validate every command against the approved Modal SDK and environment, then revise the runbook from retained operator evidence. | Runbook review plus a user-executed build/deployment later. | SDK drift or an untested operator assumption could make the procedure fail. |
| C-06 | `georeport3d/config.py`, `config/policy.yaml` | CODE-LEVEL | Typed policy defaults to L40S, constrains scaling to two containers, rejects mock in production, and models limits plus cache identity fields. | Yes. | Validate every production setting at startup, version policy changes, and prove the deployed Modal declaration matches policy. | Config tests and staging startup with production-shaped non-secret config. | Declared policy may drift from an independently edited deployment definition. |
| C-07 | `apps/api/app/main.py` health and budget routes | SCAFFOLD / CODE-LEVEL | `/health` is shallow; `/budget` reads durable PostgreSQL reservations and settled usage when persistence is configured, with an explicit in-memory fallback for isolated factory tests. | Yes. | Add readiness/dependency health, ownership scopes, and calibrated provider reconciliation. | API restart/concurrency tests and dependency-failure probes. | Healthy response may still hide failed storage/provider; the fallback must not be used as production accounting. |
| C-08 | `apps/api/app/main.py` project/upload/inventory/estimate routes | CODE-LEVEL / PARTIALLY WIRED | Creates projects, persists project-scoped PDF/DOCX uploads with one storage/database UUID, cleans duplicate/failed copies, exposes CPU inventory, and estimates bounded work through controller pricing without invoking inference. The former storage-only upload is deprecated. | Yes. | Add authentication/authorization, content validation, malware policy, private production storage, retention, durable inventory/artifact identity, and the explicit analyze transition. | PostGIS API tests with hostile files, restart, permissions, cleanup, estimate, and upload-to-inventory flow. | Untrusted content may be stored; local storage is single-host; inventory recomputation is not yet a durable snapshot. |
| C-09 | `georeport3d/storage/local.py` | SCAFFOLD / CODE-LEVEL | Uses bounded streaming, sanitized display names, SHA-256, fsync, no-clobber publication, and durable `<id>.pdf`/`<id>.docx` lookup under a resolved root. Restart lookup uses the filesystem, rejects ambiguous/non-regular entries, and surfaces legacy `<id>.bin` as unknown format. | Yes for local/dev. | Select a durable private production store, define backup/retention/encryption, persist receipts transactionally, and verify/re-upload or explicitly migrate legacy BIN entries without guessing their type. | Fault-injection, cross-format collision, restart, legacy-state, production-store integration, and recovery tests. | Single-host loss, missing lifecycle policy, or inaccessible/ambiguous legacy files after scaling. |
| C-10 | `georeport3d/services/budget.py`, database repositories, and `JobController` | CODE-LEVEL / DURABLE PATH | The ledger still owns rate arithmetic, while PostgreSQL repositories/controller own transactional admission, reservation, concurrency, settlement, and usage accounting so a process restart does not reset recorded spend. | Yes. | Calibrate rates/estimates against actual Modal usage and prove concurrent-replica, failure, cancellation, restart, and reconciliation behavior. | PostGIS concurrency/restart tests plus staging reconciliation against Modal billing/usage evidence. | Untested provider accounting or failure races could misstate spend despite the durable design. |
| C-11 | `georeport3d/services/cache.py`, cache repository, and `JobController` | CODE-LEVEL / DURABLE PATH | A canonical SHA-256 identity now includes document, figure, model/revision, prompt, preprocessing, and extraction-contract version. Controller lookup precedes budget/GPU admission and validated results persist in PostgreSQL JSONB. The contract version is encoded in the hash but has no dedicated audit column. | Yes. | Add explicit version columns where audit queries require them; prove cache hits avoid the provider, concurrent single-flight behavior, invalidation, migration, and restart. | Cache miss/hit and concurrent PostGIS integration tests; staging trace showing no remote call on hit. | Hash-only audit identity is not human-queryable; bugs in invalidation/single-flight could duplicate spend or reuse incompatible results. |
| C-12 | `georeport3d/services/controller.py` and API provider state | CODE-LEVEL / NOT API-INVOKED | `JobController` implements cache, estimate, confirmation, transactional reservation, inference, schema/domain/provenance validation, persistence, and usage reconciliation. The API injects it and uses its pricing for estimate, but no route calls `run`. | Yes. | Add authenticated `/analyze` orchestration with server-owned render/crop/prompt input and durable status/cancel/retrieval behavior; upload must remain inference-free. | End-to-end mock vertical-slice test and later one authorized Modal job. | A deploy can upload and estimate but still cannot perform governed analysis. |
| C-13 | `docs/10_API_AND_JOB_STATE.md` endpoints/state machine | CODE-LEVEL / PARTIALLY WIRED | Health, durable budget, project creation, persistent upload, CPU inventory, estimate, and read-only job status are implemented. Analyze, cancel, extraction, borehole, section, and source-page delivery remain target endpoints. | Yes as a staged contract. | Add server-owned render/crop/prompt orchestration, then implement the remaining authenticated routes. | Contract/integration tests covering every state, duplicate request, cancellation, and restart. | The vertical slice still cannot launch analysis or return persisted extraction. |
| C-14 | `georeport3d/domain/models.py`, validation, and controller provenance | CODE-LEVEL | Enforces evidence for boreholes/intervals, paired XY, bounds, and interval-vs-total-depth checks. Controller document-identity validation and server metadata stamping cover boreholes, intervals, contacts, and sections. | Yes. | Expand deterministic CRS, duplicate, overlap, provenance completeness, unit, and cross-record validation; test against adversarial field-gold data and real structured output. | Property/fixture tests, rejection corpus, and target Modal schema/provenance smoke. | Invalid or contradictory geology may be accepted; source-only provenance checks do not prove citations are visually correct. |
| C-15 | `ai/prompts/` | SCAFFOLD / NOT WIRED | Prompt constants prohibit invention and request provenance, but are not connected to a versioned task builder. | Yes. | Add prompt assembly, image/text boundaries, schemas, version IDs, token limits, and injection tests. | Golden prompt tests and extraction benchmark provenance. | Worker may receive inconsistent or unsafe prompts. |
| C-16 | `document/` | CODE-LEVEL / LOSSY ADAPTER | Lazily adapts Docling PDF/DOCX output into deterministic pages/regions; the API invokes it as CPU inventory with redacted failures. PDF parsing defaults to a non-OCR pass followed by OCR recovery for sparse real pages. Both paths disable table structure, and the adapter flattens richer Docling hierarchy/cells/references into text and coarse regions. DOCX pages are synthetic and cannot produce durable page evidence. | Yes, but not as the final extraction representation. | Preserve versioned canonical Docling JSON/table/provenance in private cloud storage; benchmark selective OCR; add supported semantic DOCX source identity or a measured cloud fixed-layout conversion; enforce a pre-conversion resource boundary. | Real PDF/DOCX field-gold benchmark, canonical-artifact regression tests, pagination/evidence tests, and resource/cost measurements. | Flattening loses structure needed for accurate logs/tables; post-conversion page guard cannot cap parse work; synthetic evidence would be false. |
| C-17 | `geology/` | SCAFFOLD / EMPTY | No coordinate transformation, borehole geometry, sections, or uncertainty engine exists. | Yes, implement incrementally. | Start with observed boreholes and deterministic CRS transforms; do not interpolate unsupported geology. | Known-coordinate transformation fixtures and visual spatial checks. | Wrong placement or invented surfaces. |
| C-18 | PostGIS ORM/migrations/repositories | CODE-LEVEL / CI-EXECUTED | SQLAlchemy metadata, Alembic baseline, unit-of-work boundaries, repositories, and PostGIS integration tests exist; the API/controller use them for project/document/job/budget/cache state. The locked CI PostGIS migration job has executed successfully on the merged baseline. This is not staging/production database evidence. | Yes. | Re-run branch/release CI, then exercise migrations, concurrency, ownership, restart/recovery, backups, and operational monitoring in an approved staging service. | Release-SHA CI logs plus staging migration head, constraints/indexes, CRUD/provenance, concurrent admission, backup and restore evidence. | CI service success does not prove production topology, permissions, upgrades, capacity, or recovery. |
| C-19 | `apps/web/README.md` | SCAFFOLD / DOCS ONLY | Declares Next.js, React, CesiumJS, React Three Fiber and viewer layers; no web source/package manifest exists. | Yes as architecture. | Implement upload/job/evidence UI and an initial lightweight borehole viewer. | Browser tests and known-coordinate screenshots/interaction recordings. | There is no usable browser product. |
| C-20 | CesiumJS plus Three.js design | SCAFFOLD / PRESERVE | CesiumJS owns geospatial context; Three.js/R3F owns engineering geometry and interaction. | Yes. | Keep both roles explicit and feed them stable API coordinates/provenance. | Coordinate fixtures and visual acceptance tests. | Role drift can duplicate transforms or create inconsistent scenes. |
| C-21 | 3D Tiles | SCAFFOLD / FUTURE | Architecture reserves 3D Tiles for large streamed datasets; first MVP does not require it. | Yes as future design, not a current gate. | Begin with JSON/GeoJSON/lightweight Three.js; add tiles only after measured scale need. | Dataset/performance benchmark justifying tiling. | Premature tiling increases complexity; claiming support now misleads users. |
| C-22 | Authentication/authorization | SCAFFOLD / NOT PRESENT | Security doc lists later controls; routes currently have no user, project ownership, or role checks. | No public deployment without it. | Implement authentication, project authorization, job/file ownership, and administrative separation. | Security integration tests and access-control review. | Unauthorized access to confidential reports and GPU spending. |
| C-23 | Rate limits/CORS/CSRF/signed URLs | SCAFFOLD / NOT PRESENT | Requirements are documented but not implemented. | Required before internet exposure. | Define trusted origins, request/rate limits, upload/download controls, and private signed access. | Staging security tests and configuration review. | Abuse, cross-origin exposure, data leakage, and budget exhaustion. |
| C-24 | `.env.example`, `.gitignore`, and benchmark artifacts | CODE-LEVEL / HISTORICAL EXPOSURE | Secret fields are placeholders; `.env*` and local data/results are ignored. The previously tracked PDF and two raw result JSON files are removed from the current tree by this branch, but normal Git deletion does not remove history or existing clones. | Yes for ignore rules; no raw artifacts in releases. | Scan the exact staged/current tree and history; document authorization/retention; separately authorize a coordinated history rewrite only if policy requires expungement. Store benchmark inputs/results privately in cloud resources. | Zero current-tree/release content findings, recorded history risk decision, and private-store access/retention review. | Confidential report/raw content may remain retrievable from history even after the merge. |
| C-25 | `pyproject.toml` | CODE-LEVEL / LOCKED | Defines supported Python and bounded dependencies; `uv.lock` now resolves the Python environment. | Yes. | Keep declarations and lock synchronized; review runtime/migration/document extras and dependency advisories from an approved CI environment. | `uv lock --check`, frozen sync on Python 3.12/3.13, build/import, and dependency/security review. | A stale or incompletely reviewed lock can reproduce the wrong environment reliably. |
| C-26 | `uv.lock` and CI lock gate | CODE-LEVEL / PRESENT | A lock file exists and normal CI checks it with `uv lock --check` before frozen sync. | Yes. | Re-run all lock/frozen-sync gates for the release commit; update only through reviewed dependency changes. | Green release-SHA Python 3.12/3.13 CI and artifact inspection. | Platform wheels, optional extras, or new advisories can still fail despite a present lock. |
| C-27 | `tests/`, Ruff/build, document, and PostGIS gates | CODE-LEVEL / CI BASELINE | Normal CI performs lock check, frozen sync, Ruff, full pytest, package build, API import, and PostGIS integration on Python 3.12/3.13 as applicable; a path-filtered document workflow runs real Docling tests. The merged baseline was green. This branch still needs its own remote results, and fakes/source tests remain non-cloud evidence. | Yes. | Require green release-SHA CI with no unexpected skips; add extraction scorer, vertical-slice, security, storage, and target-runtime tests. | Retained workflow results tied to the release commit plus separately authorized Modal/staging evidence. | Green CPU CI can coexist with cloud schema/startup failures or poor extraction accuracy. |
| C-28 | Observability | SCAFFOLD / NOT PRESENT | No structured application logging, metrics, traces, audit log, durable job events, or alert rules are implemented. | Required before production. | Add redacted structured logs, request/job IDs, state/cost metrics, provider latency/errors, and alerts. | Staging trace of one job plus redaction and alert tests. | Failures/cost spikes become invisible; confidential content may leak during ad hoc debugging. |
| C-29 | vLLM/Modal output handling | SCAFFOLD / UNVERIFIED | Worker inherits child stdout to avoid pipe deadlock; request-content redaction has not been proven against real vLLM logs. | Yes with controls. | Verify logging flags and retained logs contain no prompts, images, raw pages, model output, or tokens/secrets. | Redaction inspection from authorized smoke/build logs. | Confidential report content may enter provider logs. |
| C-30 | `.venv/` and `.superpowers/` | GENERATED / LOCAL | Local environment and implementation evidence are intentionally ignored. | Local only. | Never stage; recreate environment from the lock. Retain internal evidence locally as needed. | Staged-file inventory excludes both. | Huge, machine-specific, or sensitive files enter the release. |
| C-31 | PDF/DOCX benchmark and manual cloud evaluation | PROVISIONAL / CODE-LEVEL / NOT RUN | Exact token scoring, cloud-only input/results boundaries, and a protected manual workflow replace the invalid substring/local-artifact path. There is no field-gold corpus; the old PDF token list is provisional; no new Modal or workflow run was performed. | Yes, as a diagnostic framework. | Complete every data, metric, cloud-storage, sanitization, structured-output, DOCX, and security gate in `20_DOCUMENT_EXTRACTION_BENCHMARK_READINESS.md`. | Release-SHA field-gold evaluation with retained private raw artifacts and sanitized metrics plus reviewer/budget approvals. | A token diagnostic could be mislabeled as geological extraction accuracy or trigger unsafe handling of confidential reports. |

## Modal: code-only state and later investigation

The intended production inference path remains **Modal serverless GPU**, not a local model and not
the deterministic mock. `deployment/modal_worker.py` declares the pinned FP8 model on one exact
L40S profile with `min_containers=0`, `max_containers=2`, `buffer_containers=0`, a short scale-down
window, no retries, persistent cache volumes, bounded context/concurrency/image settings, required
JSON Schema output, Qwen thinking disabled, and one vLLM child per warm container.
`georeport3d/inference/modal_provider.py` imports the SDK lazily, requires the server-generated
response schema, and does not silently fall back to mock.

Those facts are code evidence only. They do not prove that Modal accepts every declaration, that
the CUDA/vLLM/image dependency combination builds, that the checkpoint is accessible, that it fits
an L40S, that the deployed stack accepts the generated schema and non-thinking call, or that
scale-to-zero behaves as expected. Speculative MTP is not part of the baseline. The AST tests and
fake remote tests are deliberately fake with respect to cloud behavior.

`JobController` now implements `cache lookup -> workload/cost estimate -> budget reservation ->
explicit user authorization -> Modal call -> validation -> persistence -> usage record` in source.
No `/analyze` route or server-owned prompt/render assembler invokes that controller yet. The
current upload route does not and must not invoke Modal.

The next Modal investigation should start only after a user-run build or deployment produces real
evidence. Useful evidence includes the exact command, Modal SDK version, image-build error, class
registration output, vLLM startup log, readiness result, GPU memory/timeout data, generic failure
envelope, scale-down observation, and redaction review. Do not send model weights, prompts, report
content, or credentials back as debugging evidence.

## Database and PostGIS

The former hand-written `database/schema.sql` content falsely labeled arbitrary native
easting/northing as WGS84. It has been replaced by a labeled, non-authoritative review snapshot
generated from Alembic revision `20260827_0001`. `ST_SetSRID` could not repair the old error because
it labels coordinates rather than transforms them. Native coordinates and original CRS remain
authoritative and nullable; geometry requires a coordinate pair and a positive matching SRID.

The code-level database layer now includes projects, documents, boreholes, intervals, contacts,
sections, evidence and explicit evidence links, inference jobs, usage records, and cache entries,
with repositories and transactional controller wiring. Alembic remains authoritative and the SQL
file remains only a generated review snapshot. Target PostGIS execution, migrations, concurrency,
restart/recovery, and spatial-query behavior are still separate environment gates.

A real PostGIS check is a user/environment gate. Do not treat metadata inspection or offline SQL
generation as proof that the extension, geometry indexes, upgrade, downgrade, or spatial queries
work on PostgreSQL/PostGIS.

## API, job, budget, cache, and storage wiring

The implemented API surface now includes `GET /health`, durable `GET /budget`,
`POST /projects`, project-scoped persistent upload, CPU-only inventory, and read-only job
status. Upload and inventory correctly avoid inference. The deprecated storage-only upload
route remains for compatibility. The vertical slice still needs analyze, cancel, extraction,
borehole, section, and source-page routes plus server-owned prompt/render assembly.

The API budget view is derived from durable job reservations and usage rows when PostgreSQL is
configured. The in-memory ledger remains only as the rate calculator and isolated factory-test
fallback. Estimate is implemented; analyze remains absent even though the controller now supplies
atomic cache, admission, idempotency, reconciliation, and provenance behavior.

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

`pyproject.toml` provides bounded ranges, supports Python 3.12/3.13, and has a tracked `uv.lock`.
Normal pull-request CI checks the lock, performs frozen synchronization, and runs the full CPU-only
quality matrix. This restricted workstation did not synchronize dependencies for this change; only
dependency-free syntax and source-contract tests were run locally. The branch's full pytest, Ruff,
isolated build, and FastAPI import results remain pending normal pull-request CI, not silently
passing. Do not bypass the firewall or run document/model workloads on the runner.

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

`database/schema.sql` is a special case: it is a generated review snapshot labeled with Alembic
revision `20260827_0001` and non-authoritative status. Regenerate and review it whenever the
authoritative migration changes; never treat the snapshot itself as deployment proof.

Before commit/release, inspect the exact staged file list. Generated artifacts, `.env`, credentials,
uploaded documents, model/cache files, database volumes/dumps, provider logs, and internal
`.superpowers` evidence must not be staged.

## Ordered pre-deployment gates

### A. Code-level gates

These gates require code and local dependencies but do not require a model, GPU, paid cloud call,
or production credentials.

1. Re-run the code-level SQLAlchemy/Alembic baseline and verify the labeled
   `database/schema.sql` snapshot still matches revision `20260827_0001`.
2. Re-run PostGIS repository and transaction tests for documents, observations, evidence links,
   inference jobs, usage, cache records, restart, concurrency, and failure settlement.
3. Preserve canonical Docling JSON for extraction, add versioned render/prompt assembly, define
   truthful DOCX evidence identity, and run optional document fixtures only in approved CI/cloud.
4. Re-verify the persistent cache and durable controller order: cache -> estimate ->
   reserve/confirm -> inference -> validate -> persist/reconcile.
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
10. Keep the existing `uv.lock` synchronized and reviewed; add and lock the future web manifest;
    run dependency/license/security audits appropriate to the deployment policy.
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
7. Verify the no-MTP baseline, zero automatic retries, exact L40S allocation, two-container maximum,
   zero warm minimum, and observed scale-to-zero behavior. Treat any future MTP experiment as a
   separate reviewed benchmark.
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
