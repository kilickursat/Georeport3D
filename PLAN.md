# GeoReport3D implementation plan

Updated: 2026-09-08

GeoReport3D is a pre-release backend foundation, not a deployed application. The deployment target
is Modal serverless GPU using the pinned public model `Qwen/Qwen3.6-27B-FP8` on L40S. Model and
document workloads stay in Modal; pull-request CI and developer workstations remain GPU-free.

The current application implements upload, project creation/upload, document inventory, workload
estimate, budget status, and job status. The durable `JobController` implements cache-first,
budget-authorized ordering through inference, validation, and persistence, but no `/analyze` route
or versioned prompt/render assembler calls it yet.

Legend: `[x]` implemented at code level, `[ ]` not complete. A checked cloud-related item does not
mean it has been executed in Modal unless the item explicitly says so.

## Phase 0: repository and backend foundation

- [x] Lock Python dependencies and enforce GPU-free Ruff, test, build, and API-import gates in
  GitHub Actions on Python 3.12 and 3.13.
- [x] Verify the Alembic baseline against a real PostGIS service in opt-in CI and implement durable
  repositories with unit-of-work transaction ownership.
- [x] Implement bounded streaming uploads, project/document records, SHA-256 identity, canonical
  PDF/DOCX suffixes, and development filesystem storage.
- [x] Implement domain models, evidence checks, depth rules, durable budget accounting, cache
  identity, and the job state machine.
- [x] Implement `JobController` ordering: cache lookup, estimate, confirmation, reservation,
  inference, metadata/schema/domain/provenance validation, persistence, and settlement.
- [x] Implement API routes for budget, upload, projects, project document upload, inventory,
  estimate, and job status.
- [x] Add the manual `modal-production` deployment workflow. It remains unexecuted for this
  revision and never runs on pull requests.

## Phase 1: cloud document extraction harness

### Completed in source

- [x] Add a metadata-only dataset manifest with allow-listed cloud paths, exact SHA-256 values,
  source format, page selection, and annotation maturity (`unannotated`, `provisional_tokens`, or
  `field_gold`).
- [x] Label the existing DART case `provisional_tokens`. Historic `29/30` token recall is a narrow
  diagnostic, not structured extraction accuracy; historic `10/18` identifier confirmation is
  invalid because it used substring matching.
- [x] Replace substring identifier checks with boundary-safe canonical exact matching and gate
  field precision/recall/F1 on human-reviewed `field_gold` only.
- [x] Remove the DART source PDF and raw benchmark result JSON files from the current tracked tree.
  Their older Git objects are not erased by a normal commit; history remediation is a separate
  maintainer decision.
- [x] Move benchmark input/output contracts to Modal Volumes: read-only
  `georeport3d-benchmark-data` and restricted `georeport3d-benchmark-results`. Local entrypoints do
  not upload reports, receive raw answers, or write raw result files.
- [x] Add fail-closed dataset/run-ID validation, pre-read hash verification, non-overwriting cloud
  result paths, and sanitized summaries.
- [x] Add the protected, serialized, `workflow_dispatch`-only `modal-evaluation` workflow. Pull
  requests receive no Modal/Hugging Face credentials and cannot allocate a GPU.
- [x] Align the production worker with the successful FP8/L40S startup profile: CUDA 13 library
  path, 32,768-token context, 16 sequences, one image per prompt, and no hardware fallback.
- [x] Require a Pydantic response schema through controller, provider, and worker; use vLLM JSON
  Schema structured output and disable Qwen thinking mode.
- [x] Validate document provenance across boreholes, intervals, contacts, and sections.
- [x] Document fake, stale, provisional, code-level, and blocked deployment claims in
  `docs/20_DOCUMENT_EXTRACTION_BENCHMARK_READINESS.md` and the approved cloud harness design.

### Cloud work deliberately deferred

- [ ] Verify or provision the expected DART object at
  `/benchmarks/dart-d2/cbd2_20per_geotechnicalbaselinereport.pdf` in Modal environment
  `evaluation`, with the SHA-256 recorded in `config/evaluation_datasets.yaml`.
- [ ] Verify restricted retention/access for the results Volume and required reviewers/budget for
  the GitHub `modal-evaluation` environment.
- [ ] Run one explicitly approved manual evaluation and retain only sanitized CI evidence. No run
  was triggered while implementing the harness.
- [ ] Build a representative, human-reviewed `field_gold` corpus covering born-digital and scanned
  PDFs, DOCX, tables, borehole logs, drawings, rotations, page sizes, and languages.
- [ ] Define release thresholds only after the field-gold corpus and annotation review process
  exist.

## Phase 2: complete the backend vertical slice

- [ ] Build versioned prompt/task assembly from canonical Docling JSON, preserving hierarchy,
  tables, reading order, item references, render digests, and evidence coordinates.
- [ ] Implement `/analyze` so the API passes bounded text/images and the exact
  `GeotechnicalExtraction` schema through `JobController` to the configured provider.
- [ ] Implement cancel, extraction, borehole, section, and page/evidence routes with ownership,
  idempotency, timeouts, and stable error codes.
- [ ] Replace development filesystem persistence with approved production object storage,
  retention, encryption, and access policy.
- [ ] Implement a Modal-only deterministic DOCX fixed-layout derivative with converter/version/hash
  provenance. Until then, DOCX visual/page evidence remains unsupported; synthetic ordinals are
  not printed pages.
- [ ] Implement observed-only CRS transforms and borehole/interval geometry. Never infer a CRS or
  coordinate that is absent from source evidence.
- [ ] Add authentication, authorization, tenant ownership, rate limiting, CORS/CSRF policy, and
  confidential-document lifecycle controls before any public exposure.

## Phase 3: web mapping and engineering rendering

- [ ] Create `apps/web` with Next.js/React and its own lock, type-check, lint, tests, and production
  build gates. No frontend source exists today.
- [ ] Use CesiumJS and 3D Tiles for geospatial context, terrain, camera behavior, and large spatial
  datasets.
- [ ] Use Three.js through React Three Fiber for engineering geometry: boreholes, intervals,
  contacts, sections, and uncertainty overlays.
- [ ] Share one tested coordinate/display transform between Cesium and Three.js and provide an
  evidence panel that distinguishes observed, inferred, unknown, and review-required values.

## Phase 4: separately authorized cloud proof and release

- [ ] Deploy the reviewed production worker from `main` through the protected
  `modal-production` workflow. Deployment remains separate from document evaluation.
- [ ] Capture redacted proof for exact L40S allocation, pinned model/revision, image build, vLLM
  readiness, memory fit, response-schema behavior, zero retries, maximum two containers, cost,
  and observed scale-to-zero.
- [ ] Run one bounded, explicitly authorized smoke inference after durable budget and cache-miss
  checks. Do not return source content, prompts, page images, or raw output as CI evidence.
- [ ] Run the private upload -> inventory -> analyze -> validation -> PostGIS -> evidence -> 3D
  vertical slice only after the missing backend and web steps are complete.
- [ ] Update readiness records from retained evidence, then perform a separate security/privacy
  review before considering public access.

## Current technical decisions

- **Model:** `Qwen/Qwen3.6-27B-FP8`, pinned by immutable revision. The earlier NVFP4 checkpoint is
  no longer the deployment target.
- **GPU:** L40S only, maximum two production containers. No A100 fallback is part of the evaluated
  contract.
- **Serving:** vLLM with bounded startup settings, schema-constrained output, Qwen thinking
  disabled, zero automatic retries, and scale-to-zero. Speculative MTP is not configured.
- **OCR:** adaptive OCR recovery remains available in the current document adapter. Whether OCR
  should remain the default or become a prefilter is open until a valid cloud field benchmark
  compares it with direct vision; the provisional token case cannot decide this.
- **Document truth:** canonical Docling JSON is the intended extraction intermediate. The compact
  inventory remains a routing view, not a lossless source of field truth.
- **Credentials:** GitHub stores only Modal client credentials for protected manual workflows.
  Hugging Face access lives in Modal's `huggingface-secret`; repository `HF_TOKEN` is unused by
  this topology.
- **Frontend:** CesiumJS/3D Tiles remain planned for mapping, with Three.js/R3F planned for
  engineering rendering.
