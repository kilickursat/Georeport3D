# Deployment and Hardening Plan

**Goal:** Get from a green code-level slice to a working private deployment, then close
the defects that only real evidence can settle.

**Status at the time of writing:** steps 1–7 and 13 are complete and merged. Steps 8–12
and 14–16 remain. CI is green on `main`: ruff, 311 tests, PostGIS, and the real Docling
backend.

**Spend:** every task in Phase B costs real money against the $230 cap and needs
explicit authorization at the time it is run. Nothing in Phase A or C does.

---

## What is already fixed

The defects found while implementing the durable controller are fixed and merged, not
outstanding work:

| Defect | Fixed in |
| --- | --- |
| Estimated seconds billed as actual | #12 |
| Money computed in binary floating point | #12 |
| Unexpected provider exception leaked a live reservation | #12 |
| Budget checked before the cache | #12 |
| Blind state writes could revive a cancelled job | #12 |
| Usage rows cascade-deleted with their document | #12 |
| Migration dropped a foreign key by a guessed name | #12 |
| L40S would have been billed at the L4 rate | #16 |

What remains from them is not the fix but the guard: several were caught only because a
test happened to exercise them. Task A3 adds the tests that would fail if any regressed.

---

## Phase A — Before the first deploy

These are cheap, GPU-free, and each one reduces the chance that a paid deploy has to be
repeated.

### Task A1: Isolate database tests from each other

**Files:** `tests/db/conftest.py`

The integration suite shares one database and never cleans up between tests. A job left
in `GPU_RUNNING` by one test consumed a GPU slot for every test after it, which is what
made twenty-three controller tests fail with `REJECTED` for a reason none of them named.
Individual tests now clean up in `finally` blocks, which is the same fix written twelve
times and forgotten on the thirteenth.

- [ ] Add a fixture that truncates the mutable tables between tests, ordered so foreign
      keys allow it, or wraps each test in a transaction that is rolled back.
- [ ] Prefer truncation to rollback: the admission path uses a transaction-scoped
      advisory lock and multiple sessions, and an outer transaction would change the
      concurrency semantics the tests exist to check.
- [ ] Remove the per-test `finally` cleanups that the fixture makes redundant, so the
      remaining ones are only where they carry meaning.

**Done when:** the db suite passes with `-p no:randomly` and in reverse order.

### Task A2: Make `model_revision` mean what it says

**Files:** `deployment/modal_worker.py`, `georeport3d/inference/modal_provider.py`,
`georeport3d/config.py`, `georeport3d/services/controller.py`

Open since step 3. `Settings.model_revision` defaults to `None`, so the CPU side reports
"unknown" while the container serves a pinned revision. This is not cosmetic: the cache
key is derived from `model_revision`, so every result cached before this is fixed is
keyed on a value that does not identify the model that produced it. Fixing it afterwards
invalidates that cache; fixing it first means the first deploy writes correct keys.

- [ ] Have the worker report the revision it actually loaded, from the vLLM server
      rather than from the request.
- [ ] Reject a mismatch between the requested and served revision at the provider
      boundary, with a stable code, rather than accepting the worker's word.
- [ ] Require `model_revision` in production settings, so an unpinned deployment cannot
      start.

**Done when:** a worker serving a different revision than requested fails the job
instead of caching under the requested key.

### Task A3: Regression guards for the cost defects

**Files:** `tests/services/test_budget.py`, `tests/db/test_controller.py`

- [ ] Assert every money value the controller produces is `Decimal` and never derived
      from a float multiplication — the 0.0009435000000000001 case, as a property over
      several durations rather than one example.
- [ ] Assert `profile_for` raises on an unknown GPU, and that a policy naming a GPU with
      no rate cannot construct a controller.
- [ ] Assert a provider raising an arbitrary exception leaves no live reservation, as a
      property over several exception types rather than only `RuntimeError`.

---

## Phase B — Deployment (each task needs authorization at the time)

### Task B1 (step 14): Modal deploy, no inference

Build the image, pull the pinned checkpoint into the Modal volume, register the vLLM
class. Capture SDK version, app identity, and rollback identifier.

**First real spend.** Costs build minutes and volume storage before any inference.

Two things only this can answer:

- Whether vLLM starts on an L40S with this checkpoint at all.
- Whether the 48 GB leaves the KV cache headroom the L40S was chosen for.

- [ ] Run `.github/workflows/deploy.yml` manually, from `main`, typing the confirmation.
- [ ] Record startup time, peak GPU memory, and the resolved revision.
- [ ] If startup exceeds `STARTUP_TIMEOUT_SECONDS`, raise it deliberately rather than
      retrying, and record why.

### Task B2 (step 15): One authorized smoke inference

After a persistent-budget check and a confirmed cache miss, run a single paid inference
on a non-confidential fixture.

- [ ] Record latency, GPU memory, cost, result envelope, and log-redaction evidence.
- [ ] Verify the measured seconds recorded in `usage_records` match the observed wall
      clock, which is the first end-to-end check of the measured-time fix.

### Task B3 (step 15b): Does Qwen read a geologic profile?

The question the whole document pipeline is waiting on. Send one of the nine profile
sheets from the DART report as an image and compare against the ground truth already
written in `deployment/ocr_comparison.py`.

- [ ] Compare against Docling-with-OCR on the same sheet.
- [ ] Decide the OCR default from the result, and record the decision either way.

### Task B4 (step 16): Vertical slice on one real report

Upload → inventory → analysis → validation → PostGIS → 3D view, then update
`docs/19_PRE_DEPLOYMENT_READINESS.md` and `docs/15_DEVELOPER_CHECKLIST.md` from retained
evidence only.

---

## Phase C — After real evidence

### Task C1: Settle the OCR default

Blocked on B3. If the vision model reads a sheet directly, OCR becomes an optional
prefilter and the default flips to off, removing 2.9x from every parse. If it does not,
OCR stays on and its transcription damage becomes a known, documented limit.

### Task C2: Make structural routing primary

Measured on the real report: eight of the ten recovered drawing sheets were identified,
and the geologic map on p80 and the profile on p89 were not. Most matches came from
`stationing`, a chainage convention, not from a title — which is the vocabulary working
by luck rather than by design.

- [ ] Route on structure first: sparse text plus no detected regions implies a drawing
      sheet, whatever language it is in, and that alone should reach the vision model.
- [ ] Demote the term table to a prefilter and an audit hint, which is what it is
      already documented as being in `PLAN.md`.
- [ ] Let the vision model supply the type, and keep the deterministic guess beside it
      as a disagreement a reviewer can see.

**Done when:** p80 and p89 reach the vision model with no type asserted, rather than
being typed `figure` and looking settled.

### Task C3 (step 8 remainder): Estimate and analyze endpoints

The controller is not reachable from any route. Until it is, the durable admission,
confirmation gating, and provenance checks protect nothing a user can actually invoke.

- [ ] Expose estimate and analyze, carrying `confirmed` through from the caller.
- [ ] Surface `IdempotencyConflict` and every refusal reason as stable public codes.

### Task C4 (C-22): Public exposure

Authentication, ownership checks, CORS, and rate limiting are all deferred by the
current scope. The readiness register is explicit that C-22 blocks public deployment.
Phase B produces a working *private* deployment; this is the separate plan that would be
needed before anyone else can reach it.

---

## Ordering, and why

A1 and A3 come first because they are free and stop false failures from being mistaken
for real ones during a paid deploy. A2 comes before B1 because the cache key depends on
it, and a deploy that writes keys derived from `None` has to be invalidated later.

B3 gates C1, and C1 changes what the document pipeline does on every parse, so it should
not be guessed at in advance.

C4 is last because it is a different kind of work: everything before it makes the system
correct, and C4 makes it safe to expose. Doing it earlier would be securing a system
whose behaviour is still changing.
