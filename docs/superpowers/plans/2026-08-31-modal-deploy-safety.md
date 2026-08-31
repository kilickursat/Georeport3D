# Modal Deployment Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing manual Modal deployment boundary deterministic, injection-safe, bounded, and auditable without performing a deployment or GPU/model operation.

**Architecture:** A dependency-free `georeport3d.model_identity` module owns the immutable model ID and validated 40-character lowercase hexadecimal revision. Settings, the Modal worker, the manual workflow, and offline contract tests consume that source identity; the provider treats returned identity as untrusted and requires an exact match.

**Tech Stack:** Python 3.12/3.13 stdlib `unittest`, Modal serverless L4 declarations, vLLM, GitHub Actions YAML.

**Spec:** `docs/19_PRE_DEPLOYMENT_READINESS.md`, plus the approved 2026-08-31 PR 1 scope.

## Global Constraints

- Preserve Modal serverless GPU, `L4`, scale-to-zero, one-container maximum, and zero automatic retries.
- Deploy only from the manual workflow, only from `refs/heads/main`, into GitHub environment `modal-production` and Modal environment `main`.
- The only workflow input is `confirm`, which must equal `deploy` exactly.
- Model ID is `unsloth/Qwen3.6-27B-NVFP4`; revision is `ccdaab7e68af2409599b8949a8f2685703c9bae5` and must validate as `[0-9a-f]{40}`.
- GitHub secrets are named `MODAL_ID` and `MODAL_ID_SECRET`; expose them only as runner variables `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`.
- Pin `actions/checkout@v7.0.1` to `3d3c42e5aac5ba805825da76410c181273ba90b1` and `astral-sh/setup-uv@v10.0.1` to `20cfd1bf945f4377ade1205e4dbc17946fc9a30d`, retaining tag comments.
- Do not deploy Modal, access secret values, invoke/download a model, install dependencies, run a GPU smoke, push, or open a pull request.

---

### Task 1: Lock the offline regression contract

**Files:**
- Modify: `tests/modal/test_worker.py`
- Modify: `tests/modal/test_deployment_contract.py`
- Modify: `tests/inference/test_modal_provider.py`

**Interfaces:**
- Produces tests for immutable identity, revision format, vLLM tokenizer revision, strict request revision, batch/message/content bounds, child liveness, workflow safety, permissions/action pins, and provider identity matching.

- [ ] Add focused tests before production edits.
- [ ] Run `python tests/modal/test_worker.py`, `python tests/modal/test_deployment_contract.py`, and `python tests/inference/test_modal_provider.py`.
- [ ] Record failures caused by the missing contracts, not syntax or fixture errors.

### Task 2: Centralize identity and harden the runtime boundary

**Files:**
- Create: `georeport3d/model_identity.py`
- Modify: `georeport3d/config.py`
- Modify: `.env.example`
- Modify: `deployment/modal_worker.py`
- Modify: `georeport3d/inference/modal_provider.py`

**Interfaces:**
- Produces: constants `MODEL_ID` and `MODEL_REVISION`, with import-time revision validation.
- Produces: vLLM command flags `--revision` and `--tokenizer-revision` with the same revision.
- Produces: bounded `extract_batch` requests and an `INFERENCE_FAILED` result before any completion call if the vLLM child is absent or exited.
- Consumes: returned metadata whose model ID and all request versions must match configured/originating identity.

- [ ] Import the source identity in Settings and the worker; remove deploy-time model environment overrides.
- [ ] Remove model identity overrides from `.env.example` so source remains authoritative.
- [ ] Require each request revision to equal `MODEL_REVISION` and always report the actual constants.
- [ ] Enforce explicit maximum batch, message, content-part, and content-character counts.
- [ ] Check the vLLM subprocess before each paid completion call.
- [ ] Require `returned_model_id == self._model_id` in the provider.
- [ ] Re-run all three stdlib suites to GREEN.

### Task 3: Make workflows least-privilege and deterministic

**Files:**
- Modify: `.github/workflows/deploy.yml`
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/document.yml`

**Interfaces:**
- Consumes: source-controlled model identity through a static Python import.
- Produces: one manual deploy job guarded by exact confirmation and `refs/heads/main`.

- [ ] Remove free-form model inputs and every shell interpolation of them.
- [ ] Set `environment: modal-production` and `MODAL_ENVIRONMENT: main`; map the exact GitHub secret names to Modal runner variables.
- [ ] Record identity from the source module and emit deployment/rollback identity only in a normal-success step after `modal deploy`.
- [ ] Add `permissions: { contents: read }` to CI/document workflows and replace action tags with the approved immutable SHAs plus tag comments in all three workflows.
- [ ] Keep the workflow manual-only and omit all remote/GPU smoke calls.

### Task 4: Align operator documentation and verify offline

**Files:**
- Modify: `deployment/README.md`
- Modify: `docs/19_PRE_DEPLOYMENT_READINESS.md`

**Interfaces:**
- Produces: exact GitHub secret names, GitHub/Modal environment names, environment-scoped Modal Secret/Volume lookup guidance, and explicit deferred live verification.

- [ ] Document the workflow boundary and `modal deploy --env main deployment/modal_worker.py` without executing it.
- [ ] State that code/source tests do not prove SDK, image, model, GPU, credential, or scale behavior.
- [ ] Run the three stdlib suites together, Python compile checks, available repository tests without dependency installation, and `git diff --check`.
- [ ] Review the staged file inventory for credentials, generated artifacts, or scope drift.
- [ ] Commit locally with `fix: harden manual Modal deployment` and do not push.
