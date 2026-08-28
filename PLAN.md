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
3. ⬜ **Make the worker configurable and pinned** — Add
   `secrets=[modal.Secret.from_name("huggingface-secret")]` to `@app.cls` in
   `deployment/modal_worker.py`, move `MODEL_ID` into `image.env()` so it reaches the
   container, and pin `MODEL_REVISION`. Extend `tests/modal/test_deployment_contract.py`
   to assert the secret and revision are declared.
4. ⬜ **Deploy workflow** — `.github/workflows/deploy.yml`, manual trigger on `main`
   behind an approval environment, reading `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` /
   `HF_TOKEN` from repo secrets. Never auto-deploys on merge — a deploy costs money.

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
6. ⬜ **PostGIS repositories** — Run `alembic upgrade head` against real PostGIS in
   Docker, add repositories and transaction boundaries for documents, observations,
   evidence links, jobs, usage, and cache records (C-18). Regenerate
   `database/schema.sql` from revision `20260827_0001`, labeled non-authoritative (S-01).
7. ⬜ **Durable cache and job controller** — Replace the in-memory budget ledger and
   key-only cache (C-10, C-11) with persistent, idempotent storage enforcing
   `cache → estimate → reserve → infer → validate → persist → reconcile`.
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
