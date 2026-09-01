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

13. ✅ **GPU-free end-to-end test** — Both cost guarantees are demonstrated against a
    real database in `tests/db/test_gpu_free_end_to_end.py`.
    - The provider under test is a genuine `ModalInferenceProvider` whose resolver
      raises. The resolver is the last CPU-side step before Modal is contacted, so the
      claim proved is that nothing reaches the boundary — not merely that a Python
      method went uncalled, which a fake provider would have shown.
    - Upload → inventory drives the real routes and routes a region, at zero attempts.
    - A cache hit settles `COMPLETED` at exactly `Decimal(0)` without the boundary, and
      still does so under a budget too small to admit any miss, which is what makes
      cache-first ordering a cost guarantee rather than an optimisation.
    - A deliberate miss asserts the boundary *is* reached, so the other three tests
      cannot pass by the controller having quietly stopped calling the provider.
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

## Open risks found while verifying the document backend

- **Docling layout detection was not reproducible on a synthetic PDF.** Three runs of
  the identical file with identical options recovered page 1 only, page 2 only, and
  both. A fixture of bare text lines is out of distribution for a layout model trained
  on real reports, so this may not occur on genuine documents — but it must be measured
  before the cache is trusted, because the cache key in `georeport3d/services/cache.py`
  assumes a given document and preprocess version always yield the same parse. If the
  parser is nondeterministic on real reports, cached entries can disagree with a fresh
  run. Verify with a real geotechnical PDF during step 16, and only then decide whether
  the parse output itself needs to be content-hashed into the cache key.
- **Text can be dropped without any error.** Docling attaches text to detected regions,
  so a page whose layout detection fails reports no text at all rather than failing.
  A borehole log could go unrouted because the words naming it never reached the
  classifier. Needs a real-document benchmark before extraction accuracy is claimed.
