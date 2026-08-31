# Durable Controller Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make job admission, idempotency, cache provenance, state transitions, and spend reconciliation durable and safe before any analyze API is exposed.

**Architecture:** Keep the provider call outside database transactions, but put every decision before and after it behind PostgreSQL-enforced repository operations. A transaction-scoped database lock serializes global budget/GPU-slot admission, compare-and-set updates protect persisted job state, a persisted canonical cache identity provides idempotency and single-flight, and a monotonic clock measures the provider interval for one transactional reconciliation path.

**Tech Stack:** Python 3.12/3.13, SQLAlchemy 2, PostgreSQL/PostGIS 17/3.5, Alembic, Pydantic 2, pytest.

**Spec:** `docs/07_COST_GOVERNANCE.md`, `docs/10_API_AND_JOB_STATE.md`, `docs/19_PRE_DEPLOYMENT_READINESS.md`, and the approved PR 3 controller-correctness scope dated 2026-08-31.

## Global Constraints

- Cache lookup precedes job-cap, global-budget, confirmation, GPU-slot, and provider decisions; a valid hit costs exactly zero.
- No process-local lock may be the correctness mechanism for budget or GPU-slot admission. Admission must serialize across processes through PostgreSQL in the same transaction that writes the reservation.
- `require_confirmation_above_usd` is enforced by `JobController.run(..., confirmed: bool = False)`; an unconfirmed miss above the threshold never obtains a reservation or calls the provider.
- Provider calls remain outside database transactions and are timed only with an injected monotonic callable, defaulting to `time.monotonic`.
- Every path after invocation starts records measured elapsed seconds and derived USD, then releases the live reservation by settling the job atomically, including unexpected exceptions.
- State transitions use persisted-state compare-and-set. A stale caller never revives `CANCELLED` or any other terminal state.
- Idempotency keys are bound to one persisted document/cache/provider/model/version identity. A same-identity replay returns the existing job state; a different identity raises an explicit conflict.
- Provider result metadata and all extraction/evidence document identities must match the authorized request before `PERSISTING`, `COMPLETED`, or cache insertion.
- Settled usage is an accounting record. The database refuses a domain-data deletion that would cascade-delete it until a separate archival/tombstone design exists.
- Normal CI stays GPU-free. Do not install dependencies, start PostGIS, invoke Modal/GPU/model code, push, or open a PR as part of this plan.

---

### Task 1: Commit the RED durable-safety contract

**Files:**
- Create: `docs/superpowers/plans/2026-08-31-controller-correctness.md`
- Modify: `tests/db/test_controller.py`
- Modify: `tests/db/test_repositories.py`
- Modify: `tests/db/test_metadata.py`

**Interfaces:**
- Consumes: current `JobController`, `InferenceJobRepository`, `BudgetRepository`, `CacheRepository`, and SQLAlchemy metadata.
- Produces: failing behavior tests for the exact interfaces and invariants implemented by Tasks 2-7.

- [ ] **Step 1: Add controller ordering, confirmation, replay, timing, exception, and provenance tests**

Add tests that call the wished-for controller API directly:

```python
outcome = controller.run(
    document_id=document_id,
    document_sha256=digest,
    figure_sha256=figure_digest,
    messages=messages,
    idempotency_key=key,
    estimated_seconds=600,
    confirmed=True,
)
```

Use a deterministic two-value monotonic callable around the provider call. Assert cache hits bypass exhausted policy, unconfirmed expensive misses are `REJECTED` with `CONFIRMATION_REQUIRED`, same-identity live replays return the current job without another provider call, changed identities conflict, measured rather than estimated duration drives usage, every post-invocation failure reconciles, mismatched result metadata fails, and invalid extraction/evidence document identity fails without caching.

- [ ] **Step 2: Add repository CAS, atomic admission, single-flight, and deletion tests**

Exercise two independent SQLAlchemy sessions/threads against PostgreSQL. The first admission transaction must hold the durable lock until commit; a second transaction must wait, then observe the committed reservation and refuse the ceiling-crossing estimate. Also assert `max_concurrent_gpu_jobs`, persisted-state compare-and-set, one live job per non-null cache key, and a restrictive settled-usage foreign key.

- [ ] **Step 3: Run the focused tests to verify RED in an approved dependency-backed environment**

Run:

```powershell
pytest tests/db/test_controller.py tests/db/test_repositories.py tests/db/test_metadata.py -v
```

Expected: FAIL because `confirmed`, monotonic injection, cache identity persistence, compare-and-set, serialized admission, metadata/document validation, and restrictive usage deletion do not exist yet. In the dependency-free local workspace, run `python -m compileall -q tests` instead and defer behavioral RED evidence to GitHub Actions.

- [ ] **Step 4: Commit only the plan and RED tests**

```powershell
git add docs/superpowers/plans/2026-08-31-controller-correctness.md tests/db/test_controller.py tests/db/test_repositories.py tests/db/test_metadata.py
git commit -m "test: specify durable controller safety"
```

### Task 2: Add durable cache identity and settled-accounting schema

**Files:**
- Create: `migrations/versions/20260831_0002_controller_safety.py`
- Modify: `georeport3d/db/models.py`
- Modify: `tests/db/test_metadata.py`
- Modify: `tests/db/test_migrations.py`

**Interfaces:**
- Consumes: baseline revision `20260827_0001` and existing `inference_jobs`, `usage_records`, and `inference_cache` tables.
- Produces: nullable legacy `InferenceJob.cache_key: str | None`, a PostgreSQL partial unique live-work index, and an `ON DELETE RESTRICT` usage-to-job foreign key.

- [ ] **Step 1: Verify the schema tests fail against the baseline**

Run:

```powershell
pytest tests/db/test_metadata.py tests/db/test_migrations.py -v
```

Expected: FAIL because `InferenceJob` has no `cache_key`, there is no live-cache-key uniqueness contract, and usage still cascades on job deletion.

- [ ] **Step 2: Add the SQLAlchemy metadata**

Add `cache_key` to `InferenceJob` and declare a unique PostgreSQL partial index equivalent to:

```sql
CREATE UNIQUE INDEX uq_inference_jobs_live_cache_key
ON inference_jobs (cache_key)
WHERE cache_key IS NOT NULL
  AND state NOT IN ('COMPLETED', 'REJECTED', 'CANCELLED', 'FAILED', 'BUDGET_EXCEEDED', 'TIMEOUT');
```

Keep the column nullable for rows created before the cache identity was persisted; all new controller jobs pass a non-null canonical key. Change `UsageRecord.inference_job_id` to `ForeignKey("inference_jobs.id", ondelete="RESTRICT")`.

- [ ] **Step 3: Add the forward and reverse migration**

Create revision `20260831_0002` with `down_revision = "20260827_0001"`. Add the nullable cache-key column and partial unique index, replace the usage foreign key with `ON DELETE RESTRICT`, and make downgrade restore the original cascade before dropping the index and column.

- [ ] **Step 4: Run schema and migration tests**

Run:

```powershell
pytest tests/db/test_metadata.py tests/db/test_migrations.py -v
```

Expected: PASS against an explicitly authorized loopback PostGIS test database; no Modal or GPU access occurs.

- [ ] **Step 5: Commit the schema change**

```powershell
git add georeport3d/db/models.py migrations/versions/20260831_0002_controller_safety.py tests/db/test_metadata.py tests/db/test_migrations.py
git commit -m "feat: preserve controller identity and settled spend"
```

### Task 3: Make repository state, idempotency, and cache writes atomic

**Files:**
- Modify: `georeport3d/db/repositories.py`
- Modify: `tests/db/test_repositories.py`

**Interfaces:**
- Consumes: `InferenceJob.cache_key`, the partial live-cache-key index, canonical `CacheKeyParts`, and the persisted job state.
- Produces: `InferenceJobRepository.compare_and_set_state(...) -> bool`, identity-aware `create(..., cache_key: str | None = None)`, and cache-key verification in `CacheRepository.put(...)`.

- [ ] **Step 1: Verify the repository tests fail**

Run:

```powershell
pytest tests/db/test_repositories.py -v
```

Expected: FAIL because repository transitions are unconditional, idempotency does not compare identities, concurrent equal cache keys create independent jobs, and cache rows accept mismatched key parts.

- [ ] **Step 2: Implement compare-and-set state transitions**

Implement one SQL statement with an expected-state predicate:

```python
def compare_and_set_state(
    self,
    job_id: UUID,
    expected_state: str,
    target_state: str,
    *,
    error_code: str | None = None,
    reserved_usd: Decimal | None = None,
) -> bool:
    ...  # UPDATE inference_jobs ... WHERE id = job_id AND state = expected_state
```

Return `True` only when exactly one row changed, return `False` for a stale persisted state, and raise `LookupError` only when the job ID does not exist.

- [ ] **Step 3: Bind idempotency and single-flight to canonical work identity**

Persist `cache_key` on controller-created jobs. When an idempotency conflict occurs, compare document ID, cache key, provider, model ID/revision, prompt version, and preprocess version. Return the existing row only for an exact identity match; otherwise raise `IdempotencyConflict(ValueError)`. On the live-cache-key unique conflict, return the already-live canonical job so different request keys cannot authorize duplicate GPU work.

- [ ] **Step 4: Validate cache-key parts before insertion**

Recompute `make_cache_key(CacheKeyParts(...))` in `CacheRepository.put`. Raise `CacheIdentityError(ValueError)` when the supplied key differs; do not write a row. Keep PostgreSQL `ON CONFLICT DO NOTHING` so the committed winner remains deterministic.

- [ ] **Step 5: Run repository tests**

Run:

```powershell
pytest tests/db/test_repositories.py -v
```

Expected: PASS, including two-session CAS and live-cache-key races.

- [ ] **Step 6: Commit repository atomicity**

```powershell
git add georeport3d/db/repositories.py tests/db/test_repositories.py
git commit -m "feat: make job identity and transitions atomic"
```

### Task 4: Serialize admission and enforce confirmation and GPU slots

**Files:**
- Modify: `georeport3d/db/repositories.py`
- Modify: `georeport3d/services/job_state.py`
- Modify: `georeport3d/services/controller.py`
- Modify: `tests/db/test_controller.py`
- Modify: `tests/db/test_repositories.py`

**Interfaces:**
- Consumes: a `CACHE_LOOKUP` job, durable `BudgetPosition`, policy ceiling/job cap/confirmation threshold/GPU-slot limit, and repository CAS.
- Produces: `BudgetRepository.admit_and_reserve(...) -> AdmissionDecision` and `JobController.run(..., confirmed: bool = False)`.

- [ ] **Step 1: Verify cache/confirmation/concurrency tests fail**

Run:

```powershell
pytest tests/db/test_controller.py -k "cache or confirmation or concurrent or replay" -v
pytest tests/db/test_repositories.py -k "admission" -v
```

Expected: FAIL because the current controller admits before cache lookup, ignores confirmation and GPU-slot policy, and uses an unlocked read-then-write reservation.

- [ ] **Step 2: Add one PostgreSQL transaction-scoped admission critical section**

Implement `BudgetRepository.admit_and_reserve` so the same transaction:

1. obtains a database transaction-scoped global admission lock (PostgreSQL advisory transaction lock or a locked singleton guard row),
2. reloads the job and verifies `state == "CACHE_LOOKUP"`,
3. recomputes settled spend plus all non-terminal reservations,
4. counts jobs in `GPU_AUTHORIZED` or `GPU_RUNNING`,
5. checks job cap, global/hard-stop ceiling, and `max_concurrent_gpu_jobs`, and
6. compare-and-sets the reservation and `GPU_AUTHORIZED` state.

Return stable reasons `JOB_CAP_EXCEEDED`, `BUDGET_EXHAUSTED`, `GPU_CONCURRENCY_LIMIT`, or `STALE_JOB_STATE`; never rely on `threading.Lock` for correctness.

- [ ] **Step 3: Reorder opening and enforce explicit confirmation**

For a newly created job, transition `QUEUED -> PRECHECKING -> CACHE_LOOKUP`, then read cache before any refusal. A hit compare-and-sets `COMPLETED` with zero actual cost. A miss over the confirmation threshold with `confirmed=False` compare-and-sets `REJECTED`/`CONFIRMATION_REQUIRED` before reservation. Only a confirmed/admissible miss calls `admit_and_reserve`.

Update the state machine so `CACHE_LOOKUP -> REJECTED` is legal. Do not revive or restart existing non-terminal jobs: return their persisted status. Convert changed-identity key reuse to `IdempotencyConflict`.

- [ ] **Step 4: Run controller and admission tests**

Run:

```powershell
pytest tests/db/test_controller.py tests/db/test_repositories.py -v
```

Expected: PASS for cache-first ordering, confirmation, max GPU slots, serialized ceiling admission, replay, and single-flight without a provider call on any refusal.

- [ ] **Step 5: Commit admission correctness**

```powershell
git add georeport3d/db/repositories.py georeport3d/services/job_state.py georeport3d/services/controller.py tests/db/test_controller.py tests/db/test_repositories.py
git commit -m "feat: serialize durable GPU admission"
```

### Task 5: Measure provider time and reconcile every invoked attempt

**Files:**
- Modify: `georeport3d/services/controller.py`
- Modify: `georeport3d/db/repositories.py`
- Modify: `tests/db/test_controller.py`

**Interfaces:**
- Consumes: `monotonic: Callable[[], float]`, a `GPU_RUNNING` job, and the configured GPU rate.
- Produces: one measured usage record and one terminal compare-and-set for every attempt whose provider invocation started.

- [ ] **Step 1: Verify measured-time and exception tests fail**

Run:

```powershell
pytest tests/db/test_controller.py -k "elapsed or reconcile or exception" -v
```

Expected: FAIL because the constructor cannot inject a clock, estimated seconds are recorded as actual, known early failures omit usage, and unexpected provider exceptions leave `GPU_RUNNING` reservations live.

- [ ] **Step 2: Inject and bracket the provider clock**

Add `monotonic: Callable[[], float] = time.monotonic` to `JobController.__init__`. Read it immediately before `extract_batch` and in `finally` immediately after the call returns or raises. Clamp only impossible negative deltas to zero; do not use estimated seconds as actual seconds.

- [ ] **Step 3: Consolidate transactional reconciliation**

Route success, provider-declared failure, unavailable provider, invalid cardinality, schema/provenance failure, and unexpected exception through one reconciliation boundary. In one transaction, record measured seconds/USD exactly once and compare-and-set the expected current state to `COMPLETED` or `FAILED`. Map an unexpected exception to the non-leaking stable code `PROVIDER_ERROR`.

- [ ] **Step 4: Run measured usage tests**

Run:

```powershell
pytest tests/db/test_controller.py -k "elapsed or reconcile or exception or spent" -v
```

Expected: PASS with literal measured seconds from the fake clock, USD derived at $0.000222/second for L4, and no additional live reservation after any failure.

- [ ] **Step 5: Commit reconciliation**

```powershell
git add georeport3d/services/controller.py georeport3d/db/repositories.py tests/db/test_controller.py
git commit -m "feat: reconcile measured provider usage"
```

### Task 6: Gate completion and caching on exact provenance

**Files:**
- Modify: `georeport3d/services/controller.py`
- Modify: `georeport3d/db/repositories.py`
- Modify: `tests/db/test_controller.py`
- Modify: `tests/db/test_repositories.py`

**Interfaces:**
- Consumes: authorized request identity, `InferenceResult.metadata`, and validated `GeotechnicalExtraction` evidence.
- Produces: `RESULT_METADATA_MISMATCH` or `DOCUMENT_PROVENANCE_MISMATCH` failures with measured usage and no cache row.

- [ ] **Step 1: Verify provenance tests fail**

Run:

```powershell
pytest tests/db/test_controller.py -k "metadata or provenance or document_identity" -v
pytest tests/db/test_repositories.py -k "cache_identity" -v
```

Expected: FAIL because result metadata and extraction/evidence document IDs are currently ignored and arbitrary metadata can be stored under a cache key.

- [ ] **Step 2: Compare result metadata before domain persistence**

Require exact equality for provider, model ID, model revision, prompt version, and preprocess version against the identity used to derive/authorize the job. A mismatch reconciles as `FAILED`/`RESULT_METADATA_MISMATCH` and never enters `PERSISTING`.

- [ ] **Step 3: Validate extraction and every nested evidence document identity**

After Pydantic validation, require `extraction.document_id == str(document_id)` and every borehole, interval, contact, and section evidence item to cite that same value. A mismatch reconciles as `FAILED`/`DOCUMENT_PROVENANCE_MISMATCH` and never writes cache or observations.

- [ ] **Step 4: Run provenance and cache tests**

Run:

```powershell
pytest tests/db/test_controller.py tests/db/test_repositories.py -v
```

Expected: PASS; only an identity-matching, schema-valid, provenance-valid result can be cached and completed.

- [ ] **Step 5: Commit provenance gates**

```powershell
git add georeport3d/services/controller.py georeport3d/db/repositories.py tests/db/test_controller.py tests/db/test_repositories.py
git commit -m "feat: require exact inference provenance"
```

### Task 7: Verify the complete controller-safety slice

**Files:**
- Verify: `docs/07_COST_GOVERNANCE.md`
- Verify: `docs/10_API_AND_JOB_STATE.md`
- Verify: `docs/19_PRE_DEPLOYMENT_READINESS.md`
- Verify: all files changed by Tasks 2-6.

**Interfaces:**
- Consumes: all controller-safety contracts above.
- Produces: retained code-level evidence without any API exposure or paid provider call.

- [ ] **Step 1: Run the complete GPU-free test suite in the approved CI environment**

Run:

```powershell
pytest -v
```

Expected: PASS with PostGIS integration explicitly configured by CI; Modal/provider behavior remains fake and GPU-free.

- [ ] **Step 2: Run static and package checks**

Run:

```powershell
ruff check .
python -m compileall -q georeport3d tests migrations
python -m build
```

Expected: every command exits zero with no new warnings.

- [ ] **Step 3: Review mutation coverage and the exact diff**

Confirm each realistic regression is caught: budget-before-cache, missing confirmation, process-local-only locking, stale state overwrite, replay restart, changed idempotency identity, estimated-as-actual time, unreconciled exception, metadata mismatch, foreign evidence, cascading usage deletion, and duplicate live cache work.

- [ ] **Step 4: Commit any test-only refinements made during verification**

```powershell
git add tests docs/superpowers/plans/2026-08-31-controller-correctness.md
git commit -m "test: complete controller safety coverage"
```
