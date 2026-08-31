# Plan

Scope: first deployable slice of the GeoReport3D vertical slice
(`docs/16_MVP_VERTICAL_SLICE.md`), clearing the code-level gates in
`docs/19_PRE_DEPLOYMENT_READINESS.md`. Deployment target is Modal serverless GPU.
No AWS services are used. Each step is one reviewable PR to
`github.com/kilickursat/Georeport3D`.

Hugging Face is the source of the public `unsloth/Qwen3.6-27B-NVFP4` checkpoint
(public, ungated, revision `ccdaab7e68af2409599b8949a8f2685703c9bae5`). No model
of our own is published there.

## Phase 0 — Prove the gates and automate them

1. ✅ **Lock and green the build** — Generated `uv.lock`, ran the gates the readiness
   register listed as deferred, fixed the failures, and corrected the stale offline status
   in `README.md`.
   - Output: `uv.lock` (166 packages, Python 3.13.14)
   - Ruff: 24 findings → 0. 19 auto-fixed; `File()` defaults and a deliberate `sys.path`
     insert are now configured exceptions in `pyproject.toml`.
   - Pytest: 2 failed → 184 passed, 1 skipped (PostGIS integration, opt-in).
   - Build and API import passed unchanged.
   - Follow-up for step 8: an upload with no multipart filename parameter returns FastAPI's
     raw 422 validation body instead of a stable error code.
2. ✅ **CI workflow** — `.github/workflows/ci.yml` enforces the section A gates on every
   pull request.
   - Output: `.github/workflows/ci.yml`
   - `gates` job green on Python 3.12 and 3.13: lock currency, frozen sync, Ruff,
     184 passed, build, API import.
   - `postgis` job green: `1 passed, 184 deselected` against `postgis/postgis:17-3.5`.
     This is the first execution of `alembic upgrade head` against a real database —
     PostGIS responded and all ten expected tables were created. Partial evidence for
     S-02 and C-18; repositories and transaction boundaries remain outstanding in step 6.
   - CI is GPU-free by construction: `INFERENCE_PROVIDER=mock`, no Modal credential.
3. ✅ **Make the worker configurable and pinned** — `huggingface-secret` is attached to
   `@app.cls`, `MODEL_ID` and `MODEL_REVISION` are baked into `image.env()` so they reach
   the container, and vLLM receives `--revision` so a container cannot drift to a newer
   upload of the same repository.
   - Output: `deployment/modal_worker.py`, `deployment/README.md`
   - Contract tests extended in `tests/modal/test_deployment_contract.py`; the
     `_vllm_command` assertion in `tests/modal/test_worker.py` was updated deliberately,
     since pinning changes that contract.
   - Follow-up: the reported `model_revision` in the result envelope still comes from the
     request, and `Settings.model_revision` defaults to `None`, so the CPU side reports
     "unknown" rather than the revision the container actually serves. The provider
     verifies the worker echoes the request, so the worker must not report its own value
     unilaterally — making the two agree, and rejecting a mismatch, is a contract change
     spanning both sides. It belongs with the job controller in step 7, which is where the
     cache key that consumes `model_revision` is built.
4. ✅ **Deploy workflow** — `.github/workflows/deploy.yml`, `workflow_dispatch` only,
   behind the `modal-production` environment, which requires a reviewer and permits
   protected branches only.
   - Output: `.github/workflows/deploy.yml`
   - Reads `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`. `HF_TOKEN` is deliberately not
     passed: weights are fetched inside the Modal container using the attached
     `huggingface-secret`, never on a runner, so a repository secret would do nothing.
   - Requires typing `deploy` to confirm, and rejects a moving ref for `model_revision`.
   - Never `pull_request`-triggered. The repository is public, so a fork must not be able
     to reach the Modal budget.
   - Running it is still an unexecuted, user-authorized action; step 14 is where it is
     first invoked.

## Phase 1 — Complete the backend slice

5. ✅ **Document inventory** — The empty `document/` package (C-16) now carries the
   parse contract, a lazily imported Docling adapter, deterministic figure
   classification, and a provenance-carrying inventory.
   - Output: `document/base.py`, `document/classify.py`, `document/docling_adapter.py`,
     `document/inventory.py`, `.github/workflows/document.yml`
   - 49 new tests; suite is 233 passed, 1 skipped. Docling is not imported at module
     load, so the API process and the normal CI gates stay free of it.
   - Two defects the fakes could not have caught, both found by running the real
     backend: DOCX reports no pagination at all, which silently produced an empty
     inventory; and a bounding box with no page height cannot be converted from a
     bottom-left origin, which would have placed "show source" on the wrong region.
   - `document*` was missing from the packaging include list, so the package would
     have been absent from the built wheel.
   - Follow-up: the inventory is not yet wired to any route. Step 8 consumes it.
6. ✅ **PostGIS repositories** — Documents, observations, evidence links, jobs, usage,
   and cache records can now be read and written (C-18). `database/schema.sql` is
   regenerated from revision `20260827_0001` behind a non-authoritative banner (S-01).
   - Output: `georeport3d/db/session.py`, `georeport3d/db/repositories.py`,
     `tests/db/conftest.py`, `tests/db/test_repositories.py`, `database/schema.sql`
   - 11 new tests, green against real PostGIS in CI: `12 passed, 1 skipped,
     231 deselected` in the `postgis` job.
   - Repositories never commit; `unit_of_work` owns the transaction, so a cache
     entry, usage record, and job transition commit together or not at all.
   - Enforced in the repository rather than trusted to callers: evidence must belong
     to the document being persisted; geometry is written only with an explicit SRID,
     never one derived from CRS text; a repeated idempotency key returns the existing
     job with its original reservation.
   - Follow-up: the borehole geometry column stays null until an SRID can be resolved
     deterministically from the document, which is step 10.
7. ✅ **Durable cache and job controller** — Budget admission and the result cache are
   now durable, and the ordered pipeline is enforced by a state machine (C-10, C-11).
   - Output: `georeport3d/services/job_state.py`, `georeport3d/services/controller.py`,
     `BudgetRepository` in `georeport3d/db/repositories.py`,
     `tests/services/test_job_state.py`, `tests/db/test_controller.py`
   - 22 new tests. `postgis` job green at `23 passed, 1 skipped, 243 deselected`.
   - The ledger keeps its role as the GPU rate calculator; it is no longer the
     accountant. Spend and reservations previously lived in process memory, so a
     restart reset recorded spend to zero and freed the whole budget again.
   - Ordering is structural: `GPU_RUNNING` is unreachable except through
     `CACHE_LOOKUP` and `GPU_AUTHORIZED`, so no caller can shortcut to spending. A
     cache hit settles without authorising a GPU, proven with a provider that fails
     if called. A refused job holds no reservation.
   - A result failing schema validation is never cached and never returned. A failed
     attempt still records its spend, since a GPU that ran consumed time.
   - Fixed: `InferenceJobRepository.create` defaulted to `PENDING`, a state absent
     from `docs/10` and unenforced by the column, so jobs were created in a state the
     machine cannot advance out of.
   - Follow-up: not wired to any route yet (step 8). `model_revision` still comes
     from settings rather than from what the container serves, so the step 3
     follow-up remains open.
8. ⬜ **Job and extraction endpoints** — Implement the inventory, estimate, analyze,
   status, cancel, extraction, borehole, section, and page routes from
   `docs/10_API_AND_JOB_STATE.md` (C-13) with idempotency keys, timeouts, and stable
   error codes. Wires the provider on `app.state` that no route currently calls (C-12).
9. ⬜ **Versioned prompt assembly** — Connect `ai/prompts/` to a versioned task builder
   with schemas, image/text boundaries, token limits, and prompt-injection tests (C-15).
10. ⬜ **Observed borehole geometry** — Fill the empty `geology/` package (C-17) with
    deterministic CRS transforms and borehole geometry for observed data only.

## Phase 2 — The web app

11. ⬜ **Next.js scaffold** — Create the actual app under `apps/web/` (C-19) with a
    lockfile; add type-check, lint, unit tests, and production build to CI.
12. ⬜ **Upload, evidence, and 3D viewer** — Upload → job status → evidence UI, with
    CesiumJS for geospatial context and Three.js/R3F for borehole geometry sharing one
    tested display-coordinate pipeline (C-20). Evidence panel visibly distinguishes
    observed, inferred, and unknown.

## Phase 3 — Deploy

13. ⬜ **GPU-free end-to-end test** — Prove with the mock provider that upload alone
    never invokes inference and that a cache hit never reaches the remote boundary.
14. ⬜ **Modal deploy, no inference** — From CI with explicit approval: build the image,
    pull the pinned checkpoint into the Modal volume, register the vLLM class, capture
    SDK version, app identity, and rollback identifier.
15. ⬜ **One authorized smoke inference** — After a persistent-budget check and confirmed
    cache miss, run a single paid inference on a non-confidential fixture. Record
    latency, GPU memory, cost, result envelope, and log-redaction evidence.
16. ⬜ **Vertical slice and evidence update** — Run upload → inventory → analysis →
    validation → PostGIS → 3D view on one permitted real report, then update
    `docs/19_PRE_DEPLOYMENT_READINESS.md` and `docs/15_DEVELOPER_CHECKLIST.md` from
    retained evidence only.

## Constraints this scope carries

- **No public exposure.** This scope defers authentication, ownership checks, CORS/CSRF,
  and rate limiting. The register is explicit that C-22 blocks public deployment. Steps
  14–16 produce a working private deployment; public exposure needs a follow-up plan.
- **Steps 14–16 spend real money** against the `$230` cap, including build and storage
  charges before any inference. Each requires explicit authorization at the time.
- **Step 1 may reshuffle Phase 1.** The full test suite has never been run. Real
  breakage gets reported before feature work begins, not folded in silently.

## Document backend: risks measured against a real report

Both risks below were opened against a synthetic fixture and have now been measured on
a real 105-page geotechnical baseline report (DART D2, 20% design) using
`deployment/docling_bench.py` on Modal — three parses per run, fresh converter each
time. The report is third-party and gitignored, so these findings are the retained
evidence, not the document.

- **✅ Closed — layout detection is reproducible on real documents.** Three runs
  produced zero structural differences: identical page count, per-page text hashes,
  region counts, bounding boxes, and captions. The nondeterminism seen earlier was an
  artefact of the synthetic fixture — bare text lines are out of distribution for a
  layout model trained on real reports. Determinism also held with the OCR recovery
  pass active. The cache key in `georeport3d/services/cache.py` may therefore keep
  assuming that a given document and preprocess version yield the same parse; the parse
  output does not need to be content-hashed into the key.
- **⚠️ Confirmed and mitigated, not eliminated — text was silently dropped.** The risk
  was real and worse than described. Twenty-one pages returned under 100 characters
  against a document median of 2,584, and the ten worst were the report's primary
  geological source: the geologic map (p80) and the nine general geologic profile sheets
  (p83–91) returned 3–88 characters and **zero regions**. The pipeline was blind to the
  subsurface interpretation, with no bounding box for any citation to point at, and
  reported no error while doing it.

  Mitigated in `document/` v2 by three changes, each verified on the same report:
  structural sparse-page triage (`SPARSE_TEXT_CHARS`, absolute rather than relative,
  because a relative threshold flags nothing on a fully scanned document), an adaptive
  second OCR pass over only the sparse pages, and a whole-page fallback region so a
  sheet the layout model saw nothing on is still citable. Pages under 100 characters
  fell from 21 to 3, and all three remaining are genuine section dividers. The drawing
  sheets went from 3–88 characters and no region to 1,287–1,872 characters with one
  region each. Cost: 2.9× parse time.

  It is mitigated rather than closed because the fallback is a whole page, not a located
  region, so a citation against one is coarser than a citation against a detected figure.
  `ParsedFigure.origin` records which kind a region is precisely so this stays visible
  downstream rather than being averaged away.

- **⚠️ New — page text cannot identify a region.** Not previously on this list, and only
  visible against a real document. v1 assigned a geological identity whenever a
  vocabulary term appeared anywhere in a page's text. On this report that produced
  nineteen `borehole_log` regions of which **nineteen were wrong**: every one sat on a
  page of body prose that merely discussed boring logs, and not one was a borehole log.
  In reports of this genre the phrase appears on dozens of narrative pages.

  Fixed in v2 (`PREPROCESS_VERSION` bumped, since it is part of the cache key):
  identification comes only from a region's own caption; page text can corroborate a
  caption but no longer name a region alone, and is retained as an auditable `hint` when
  it stands alone. False `borehole_log` routings went 19 → 0, and `map` went from 5 (one
  correct) to 1 (the correct one). The single exception is a whole-page fallback region,
  where the page *is* the region and its text is the sheet's own title block.

- **⚠️ Open — the vocabulary is a fallback, not the mechanism.** `document/terms.py`
  now normalizes Unicode, folds regional and morphological variants, and carries terms
  in five languages, which is what made the US spellings on this report ("geologic",
  "boring log", "profile") match at all when the v1 UK-only vocabulary missed every one.
  But no term table generalizes to every house style, language, and drafting convention
  in this genre. The mechanism that does generalize is structural and language-free:
  sparse text plus no detected regions implies a drawing sheet, which routes to the
  vision model. The vocabulary should stay a cheap prefilter and a source of audit
  hints, and must not become the thing accuracy depends on.

- **⚠️ Open, pending step 14 — whether OCR should be on by default.** The recovery pass
  is what makes those ten sheets readable today, and it costs 2.9× parse time. But
  `unsloth/Qwen3.6-27B-NVFP4` is a vision-language model, so it can read a rendered
  sheet directly, with spatial layout intact and without OCR's second error stage —
  which on this report already showed transcription damage (a dropped apostrophe in the
  offset `151' RT`). If the vision model reads a geologic profile well, OCR becomes an
  optional prefilter and the default should flip to off. That cannot be decided without
  the step-14 deploy, so the default stays on until it is measured.
