"""The controller's ordering is the cost control, so each guard is asserted."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from threading import Event, Lock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from georeport3d.config import (
    CANONICAL_CACHE_KEY_FIELDS,
    BudgetPolicy,
    CachePolicy,
    LimitsPolicy,
    ModalPolicy,
    Policy,
    Settings,
)
from georeport3d.db.models import UsageRecord
from georeport3d.db.repositories import (
    BudgetRepository,
    CacheRepository,
    DocumentRepository,
    InferenceJobRepository,
    ProjectRepository,
)
from georeport3d.db.session import unit_of_work
from georeport3d.inference.base import (
    InferenceFailure,
    InferenceMetadata,
    InferenceRequest,
    InferenceResult,
    InferenceUnavailableError,
)
from georeport3d.services.budget import BudgetLedger
from georeport3d.services.controller import JobController
from georeport3d.services.job_state import TERMINAL_STATES

pytestmark = pytest.mark.integration

def _valid_output(document_id: UUID | str) -> dict[str, object]:
    return {
        "document_id": str(document_id),
        "boreholes": [],
        "contacts": [],
        "sections": [],
        "notes": [],
        "extraction_confidence": 0.0,
    }


def _output_with_evidence(
    document_id: UUID | str,
    evidence_document_id: UUID | str,
) -> dict[str, object]:
    output = _valid_output(document_id)
    output["boreholes"] = [
        {
            "borehole_id": "BH-1",
            "evidence": [
                {
                    "document_id": str(evidence_document_id),
                    "page_number": 1,
                    "source_type": "borehole_log",
                    "confidence": 0.9,
                }
            ],
        }
    ]
    return output


class _RecordingProvider:
    """Records every call so 'never reached the GPU' can be asserted directly."""

    def __init__(
        self,
        result: InferenceResult | None = None,
        raises: Exception | None = None,
        results: list[InferenceResult] | None = None,
    ) -> None:
        self.calls: list[list[InferenceRequest]] = []
        self._result = result
        self._raises = raises
        self._results = results

    def extract_batch(self, requests):  # noqa: ANN001, ANN201 - matches the Protocol
        self.calls.append(list(requests))
        if self._raises is not None:
            raise self._raises
        if self._results is not None:
            return list(self._results)
        assert self._result is not None
        return [self._result]


class _BlockingProvider(_RecordingProvider):
    """Hold the first invocation while a replay observes its durable state."""

    def __init__(self, result: InferenceResult) -> None:
        super().__init__(result=result)
        self.started = Event()
        self.release = Event()
        self._call_lock = Lock()

    def extract_batch(self, requests):  # noqa: ANN001, ANN201 - matches the Protocol
        with self._call_lock:
            self.calls.append(list(requests))
            call_number = len(self.calls)
        if call_number == 1:
            self.started.set()
            if not self.release.wait(timeout=5):
                raise AssertionError("test did not release the provider")
        assert self._result is not None
        return [self._result]


class _SequenceClock:
    """A strict monotonic fake: one timestamp before and one after invocation."""

    def __init__(self, *values: float) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        try:
            return next(self._values)
        except StopIteration as exc:  # pragma: no cover - signals an implementation regression
            raise AssertionError("controller read the provider clock too many times") from exc


def _metadata(settings: Settings) -> InferenceMetadata:
    return InferenceMetadata(
        provider="mock",
        model_id=settings.model_id,
        model_revision=settings.model_revision,
        prompt_version=settings.prompt_version,
        preprocess_version=settings.preprocess_version,
    )


def _settings() -> Settings:
    return Settings(app_env="test", inference_provider="mock")


def _policy(
    global_usd: float = 230.0,
    hard_stop: float = 220.0,
    job_cap: float = 5.0,
    confirmation_above: float = 1.0,
    max_concurrent_gpu_jobs: int = 1,
) -> Policy:
    return Policy(
        budget=BudgetPolicy(
            global_usd=global_usd,
            default_job_cap_usd=job_cap,
            require_confirmation_above_usd=confirmation_above,
            hard_stop_usd=hard_stop,
        ),
        limits=LimitsPolicy(
            max_file_mb=250,
            max_pages=500,
            max_ai_pages_per_job=100,
            max_concurrent_gpu_jobs=max_concurrent_gpu_jobs,
        ),
        cache=CachePolicy(enabled=True, key_fields=list(CANONICAL_CACHE_KEY_FIELDS)),
        # Pinned to L4 so the rate assertions below stay about measured-time
        # arithmetic rather than about which GPU the project currently deploys.
        modal=ModalPolicy(gpu="L4"),
    )


def _controller(
    session_factory: sessionmaker[Session],
    provider: _RecordingProvider,
    policy: Policy | None = None,
    monotonic: Callable[[], float] | None = None,
) -> JobController:
    options: dict[str, object] = {}
    if monotonic is not None:
        options["monotonic"] = monotonic
    return JobController(
        session_factory=session_factory,
        provider=provider,
        policy=policy or _policy(),
        settings=_settings(),
        ledger=BudgetLedger(),
        **options,
    )


def _document(session_factory: sessionmaker[Session]) -> tuple[UUID, str]:
    with unit_of_work(session_factory) as session:
        project = ProjectRepository(session).create(name=f"project-{uuid4()}")
        digest = uuid4().hex + uuid4().hex[:32]
        document, _ = DocumentRepository(session).add(project.id, "report.pdf", digest, 10)
        return document.id, digest


def _run(controller: JobController, document_id: UUID, digest: str, **overrides):  # noqa: ANN003
    payload = {
        "document_id": document_id,
        "document_sha256": digest,
        "figure_sha256": "f" * 64,
        "messages": [{"role": "user", "content": "extract"}],
        "idempotency_key": f"key-{uuid4()}",
        "estimated_seconds": 30.0,
    }
    payload.update(overrides)
    return controller.run(**payload)


def _seed_cache(
    session_factory: sessionmaker[Session],
    controller: JobController,
    document_id: UUID,
    digest: str,
) -> dict[str, object]:
    settings = _settings()
    output = _valid_output(document_id)
    with unit_of_work(session_factory) as session:
        inserted = CacheRepository(session).put(
            cache_key=controller.cache_key_for(digest, "f" * 64),
            document_sha256=digest,
            figure_sha256="f" * 64,
            model_id=settings.model_id,
            model_revision=settings.model_revision,
            prompt_version=settings.prompt_version,
            preprocess_version=settings.preprocess_version,
            result=output,
        )
        assert inserted is True
    return output


def _usage_for_job(
    session_factory: sessionmaker[Session], job_id: UUID
) -> list[UsageRecord]:
    with unit_of_work(session_factory) as session:
        return list(
            session.scalars(
                select(UsageRecord).where(UsageRecord.inference_job_id == job_id)
            )
        )


def _settle_live_test_job(
    session_factory: sessionmaker[Session], idempotency_key: str
) -> None:
    """Keep an intentionally RED exception path from contaminating later tests."""
    with unit_of_work(session_factory) as session:
        repository = InferenceJobRepository(session)
        job = repository.get_by_idempotency_key(idempotency_key)
        if job is not None and job.state not in TERMINAL_STATES:
            repository.set_state(job.id, "FAILED", error_code="TEST_CLEANUP")


def test_a_miss_runs_the_pipeline_and_records_what_it_spent(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, digest = _document(session_factory)
    settings = _settings()
    output = _valid_output(document_id)
    provider = _RecordingProvider(
        InferenceResult(ok=True, metadata=_metadata(settings), output=output)
    )
    controller = _controller(session_factory, provider)

    outcome = _run(controller, document_id, digest)

    assert outcome.state == "COMPLETED"
    assert outcome.cache_hit is False
    assert outcome.output == output
    assert outcome.actual_usd is not None and outcome.actual_usd > 0
    assert len(provider.calls) == 1

    with unit_of_work(session_factory) as session:
        key = controller.cache_key_for(digest, "f" * 64)
        assert CacheRepository(session).get(key) == output
        # The reservation is released by settling, leaving only measured spend.
        position = BudgetRepository(session).position(TERMINAL_STATES)
        assert position.settled_usd >= outcome.actual_usd


def test_a_second_request_hits_the_cache_and_never_reaches_the_provider(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, digest = _document(session_factory)
    settings = _settings()
    output = _valid_output(document_id)
    first = _RecordingProvider(
        InferenceResult(ok=True, metadata=_metadata(settings), output=output)
    )
    _run(_controller(session_factory, first), document_id, digest)

    # A provider that fails if touched proves the second run costs nothing.
    second = _RecordingProvider(raises=AssertionError("provider must not be called"))
    outcome = _run(_controller(session_factory, second), document_id, digest)

    assert outcome.state == "COMPLETED"
    assert outcome.cache_hit is True
    assert outcome.actual_usd == Decimal(0)
    assert outcome.output == output
    assert second.calls == []


def test_an_estimate_over_the_job_cap_is_refused_before_any_call(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, digest = _document(session_factory)
    provider = _RecordingProvider(raises=AssertionError("provider must not be called"))
    controller = _controller(session_factory, provider, policy=_policy(job_cap=0.0001))

    outcome = _run(controller, document_id, digest)

    assert outcome.state == "BUDGET_EXCEEDED"
    assert outcome.error_code == "JOB_CAP_EXCEEDED"
    assert provider.calls == []


def test_an_exhausted_budget_is_refused_before_any_call(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, digest = _document(session_factory)

    # The ceiling cannot simply be set below one estimate: policy requires the job
    # cap to be at or under the hard stop, so a tiny ceiling would trip the cap
    # first. Exhaustion has to come from spend that is genuinely already committed,
    # which is exactly what the durable position is for.
    ceiling = 5.0
    with unit_of_work(session_factory) as session:
        seeded, _ = InferenceJobRepository(session).create(
            document_id=document_id,
            idempotency_key=f"seed-{uuid4()}",
            provider="mock",
            model_id="m",
            prompt_version="v1",
            preprocess_version="v1",
            estimated_usd=ceiling,
            reserved_usd=ceiling,
            state="GPU_RUNNING",
        )

    provider = _RecordingProvider(raises=AssertionError("provider must not be called"))
    controller = _controller(
        session_factory,
        provider,
        policy=_policy(global_usd=ceiling, hard_stop=ceiling, job_cap=ceiling),
    )

    outcome = _run(controller, document_id, digest)

    assert outcome.state == "BUDGET_EXCEEDED"
    assert outcome.error_code == "BUDGET_EXHAUSTED"
    assert provider.calls == []

    # The position is global, so an unsettled seed would eat every later test's
    # headroom. Settling it releases the reservation.
    with unit_of_work(session_factory) as session:
        InferenceJobRepository(session).set_state(seeded.id, "CANCELLED")


def test_a_refused_job_holds_no_reservation(session_factory: sessionmaker[Session]) -> None:
    document_id, digest = _document(session_factory)
    with unit_of_work(session_factory) as session:
        before = BudgetRepository(session).position(TERMINAL_STATES)

    controller = _controller(
        session_factory,
        _RecordingProvider(raises=AssertionError("unreachable")),
        policy=_policy(job_cap=0.0001),
    )
    _run(controller, document_id, digest)

    with unit_of_work(session_factory) as session:
        after = BudgetRepository(session).position(TERMINAL_STATES)
    assert after.reserved_usd == before.reserved_usd


def test_an_unavailable_provider_fails_the_job_without_caching(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, digest = _document(session_factory)
    provider = _RecordingProvider(raises=InferenceUnavailableError("worker unavailable"))
    controller = _controller(session_factory, provider)

    outcome = _run(controller, document_id, digest)

    assert outcome.state == "FAILED"
    assert outcome.error_code == "PROVIDER_UNAVAILABLE"
    with unit_of_work(session_factory) as session:
        assert CacheRepository(session).get(controller.cache_key_for(digest, "f" * 64)) is None


def test_a_result_failing_validation_is_never_cached(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, digest = _document(session_factory)
    settings = _settings()
    # Structurally a success, but not a valid extraction.
    provider = _RecordingProvider(
        InferenceResult(
            ok=True,
            metadata=_metadata(settings),
            output={"boreholes": "not-a-list"},
        )
    )
    controller = _controller(session_factory, provider)

    outcome = _run(controller, document_id, digest)

    assert outcome.state == "FAILED"
    assert outcome.error_code == "SCHEMA_VALIDATION_FAILED"
    assert outcome.output is None
    with unit_of_work(session_factory) as session:
        assert CacheRepository(session).get(controller.cache_key_for(digest, "f" * 64)) is None


def test_a_failed_attempt_still_records_its_spend(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, digest = _document(session_factory)
    settings = _settings()
    provider = _RecordingProvider(
        InferenceResult(
            ok=False,
            metadata=_metadata(settings),
            error=InferenceFailure(code="INVALID_MODEL_JSON", message="bad json"),
        )
    )
    # The clock is stated rather than measured. Now that usage records the real
    # elapsed interval, a fake provider that returns in microseconds genuinely costs
    # less than the sixth decimal place the column stores, so measured spend would
    # round to zero and this test could not see the record it exists to check.
    controller = _controller(
        session_factory, provider, monotonic=_SequenceClock(0.0, 30.0)
    )
    with unit_of_work(session_factory) as session:
        before = BudgetRepository(session).position(TERMINAL_STATES)

    outcome = _run(controller, document_id, digest)

    # A GPU that ran and produced an unusable answer still consumed time.
    assert outcome.state == "FAILED"
    assert outcome.error_code == "INVALID_MODEL_JSON"
    assert outcome.actual_usd is not None and outcome.actual_usd > 0
    with unit_of_work(session_factory) as session:
        after = BudgetRepository(session).position(TERMINAL_STATES)
    assert after.settled_usd > before.settled_usd


def test_a_replayed_key_returns_the_settled_job_without_running_again(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, digest = _document(session_factory)
    settings = _settings()
    key = f"key-{uuid4()}"
    provider = _RecordingProvider(
        InferenceResult(
            ok=True,
            metadata=_metadata(settings),
            output=_valid_output(document_id),
        )
    )
    controller = _controller(session_factory, provider)

    first = _run(controller, document_id, digest, idempotency_key=key)
    second = _run(controller, document_id, digest, idempotency_key=key)

    assert first.job_id == second.job_id
    assert second.state == "COMPLETED"
    # One provider call across both requests.
    assert len(provider.calls) == 1


def test_jobs_are_created_in_the_documented_entry_state(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, _ = _document(session_factory)
    with unit_of_work(session_factory) as session:
        job, created = InferenceJobRepository(session).create(
            document_id=document_id,
            idempotency_key=f"key-{uuid4()}",
            provider="mock",
            model_id="m",
            prompt_version="v1",
            preprocess_version="v1",
            estimated_usd=1,
            reserved_usd=0,
        )
        assert created is True
        # PENDING is not part of the documented machine and cannot be advanced.
        assert job.state == "QUEUED"


def test_cache_lookup_precedes_job_cap_refusal(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, digest = _document(session_factory)
    provider = _RecordingProvider(raises=AssertionError("provider must not be called"))
    controller = _controller(
        session_factory,
        provider,
        policy=_policy(job_cap=0.0001),
    )
    cached = _seed_cache(session_factory, controller, document_id, digest)

    outcome = _run(controller, document_id, digest, estimated_seconds=30.0)

    assert outcome.state == "COMPLETED"
    assert outcome.cache_hit is True
    assert outcome.actual_usd == Decimal(0)
    assert outcome.output == cached
    assert provider.calls == []


def test_cache_lookup_precedes_exhausted_budget_refusal(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, digest = _document(session_factory)
    seed_key = f"exhaustion-{uuid4()}"
    with unit_of_work(session_factory) as session:
        InferenceJobRepository(session).create(
            document_id=document_id,
            idempotency_key=seed_key,
            provider="mock",
            model_id="m",
            prompt_version="v1",
            preprocess_version="v1",
            estimated_usd=230,
            reserved_usd=230,
            state="GPU_RUNNING",
        )

    provider = _RecordingProvider(raises=AssertionError("provider must not be called"))
    controller = _controller(
        session_factory,
        provider,
        policy=_policy(global_usd=230, hard_stop=230, job_cap=5),
    )
    cached = _seed_cache(session_factory, controller, document_id, digest)

    try:
        outcome = _run(controller, document_id, digest)
        assert outcome.state == "COMPLETED"
        assert outcome.cache_hit is True
        assert outcome.actual_usd == Decimal(0)
        assert outcome.output == cached
        assert provider.calls == []
    finally:
        _settle_live_test_job(session_factory, seed_key)


def test_expensive_cache_miss_requires_explicit_confirmation(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, digest = _document(session_factory)
    provider = _RecordingProvider(raises=AssertionError("provider must not be called"))
    controller = _controller(
        session_factory,
        provider,
        policy=_policy(confirmation_above=0.001),
    )

    outcome = _run(controller, document_id, digest, confirmed=False)

    assert outcome.state == "REJECTED"
    assert outcome.error_code == "CONFIRMATION_REQUIRED"
    assert outcome.actual_usd is None
    assert provider.calls == []
    with unit_of_work(session_factory) as session:
        position = BudgetRepository(session).position(TERMINAL_STATES)
        job = InferenceJobRepository(session).get(outcome.job_id)
        assert job is not None
        assert job.reserved_usd == Decimal(0)
        assert position.reserved_usd >= 0


def test_explicit_confirmation_allows_an_expensive_cache_miss(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, digest = _document(session_factory)
    settings = _settings()
    provider = _RecordingProvider(
        InferenceResult(
            ok=True,
            metadata=_metadata(settings),
            output=_valid_output(document_id),
        )
    )
    controller = _controller(
        session_factory,
        provider,
        policy=_policy(confirmation_above=0.001),
    )

    outcome = _run(controller, document_id, digest, confirmed=True)

    assert outcome.state == "COMPLETED"
    assert len(provider.calls) == 1


def test_max_concurrent_gpu_jobs_refuses_a_distinct_live_job(
    session_factory: sessionmaker[Session],
) -> None:
    live_document_id, _ = _document(session_factory)
    document_id, digest = _document(session_factory)
    live_key = f"live-{uuid4()}"
    request_key = f"request-{uuid4()}"
    with unit_of_work(session_factory) as session:
        InferenceJobRepository(session).create(
            document_id=live_document_id,
            idempotency_key=live_key,
            provider="mock",
            model_id="m",
            prompt_version="v1",
            preprocess_version="v1",
            estimated_usd=0.01,
            reserved_usd=0.01,
            state="GPU_RUNNING",
        )

    provider = _RecordingProvider(raises=AssertionError("provider must not be called"))
    controller = _controller(
        session_factory,
        provider,
        policy=_policy(max_concurrent_gpu_jobs=1),
    )

    try:
        outcome = _run(
            controller,
            document_id,
            digest,
            idempotency_key=request_key,
        )
        assert outcome.state in TERMINAL_STATES
        assert outcome.error_code == "GPU_CONCURRENCY_LIMIT"
        assert provider.calls == []
    finally:
        _settle_live_test_job(session_factory, live_key)
        _settle_live_test_job(session_factory, request_key)


def test_inflight_idempotency_replay_returns_existing_status(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, digest = _document(session_factory)
    settings = _settings()
    key = f"key-{uuid4()}"
    provider = _BlockingProvider(
        InferenceResult(
            ok=True,
            metadata=_metadata(settings),
            output=_valid_output(document_id),
        )
    )
    controller = _controller(session_factory, provider)

    with ThreadPoolExecutor(max_workers=1) as executor:
        first_future = executor.submit(
            _run,
            controller,
            document_id,
            digest,
            idempotency_key=key,
        )
        assert provider.started.wait(timeout=5), "first invocation never reached provider"
        try:
            replay = _run(controller, document_id, digest, idempotency_key=key)
        finally:
            provider.release.set()
        first = first_future.result(timeout=5)

    assert replay.job_id == first.job_id
    assert replay.state == "GPU_RUNNING"
    assert len(provider.calls) == 1


@pytest.mark.parametrize("identity_change", ["document", "figure"])
def test_idempotency_key_reuse_for_different_work_is_rejected(
    session_factory: sessionmaker[Session],
    identity_change: str,
) -> None:
    document_id, digest = _document(session_factory)
    other_document_id, other_digest = _document(session_factory)
    settings = _settings()
    key = f"key-{uuid4()}"
    provider = _RecordingProvider(
        InferenceResult(
            ok=True,
            metadata=_metadata(settings),
            output=_valid_output(document_id),
        )
    )
    controller = _controller(session_factory, provider)
    _run(controller, document_id, digest, idempotency_key=key)

    changed = {
        "document_id": other_document_id if identity_change == "document" else document_id,
        "digest": other_digest if identity_change == "document" else digest,
        "figure_sha256": "e" * 64 if identity_change == "figure" else "f" * 64,
    }
    with pytest.raises(ValueError) as caught:
        _run(
            controller,
            changed["document_id"],
            changed["digest"],
            idempotency_key=key,
            figure_sha256=changed["figure_sha256"],
        )

    assert caught.type.__name__ == "IdempotencyConflict"
    assert len(provider.calls) == 1


def test_stale_advance_cannot_revive_a_cancelled_job(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, _ = _document(session_factory)
    key = f"key-{uuid4()}"
    with unit_of_work(session_factory) as session:
        job, _ = InferenceJobRepository(session).create(
            document_id=document_id,
            idempotency_key=key,
            provider="mock",
            model_id="m",
            prompt_version="v1",
            preprocess_version="v1",
            estimated_usd=1,
            reserved_usd=1,
            state="GPU_AUTHORIZED",
        )
        job_id = job.id
        InferenceJobRepository(session).set_state(job_id, "CANCELLED")

    controller = _controller(
        session_factory,
        _RecordingProvider(raises=AssertionError("provider must not be called")),
    )
    stale_error: Exception | None = None
    try:
        try:
            controller._advance(job_id, "GPU_AUTHORIZED", "GPU_RUNNING")
        except Exception as exc:  # noqa: BLE001 - either a no-op or an explicit stale error is safe
            stale_error = exc

        with unit_of_work(session_factory) as session:
            persisted = InferenceJobRepository(session).get(job_id)
            assert persisted is not None
            assert persisted.state == "CANCELLED"
        if stale_error is not None:
            assert stale_error.__class__.__name__ == "StaleJobState"
    finally:
        _settle_live_test_job(session_factory, key)


def test_measured_provider_elapsed_time_drives_actual_usage(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, digest = _document(session_factory)
    settings = _settings()
    provider = _RecordingProvider(
        InferenceResult(
            ok=True,
            metadata=_metadata(settings),
            output=_valid_output(document_id),
        )
    )
    controller = _controller(
        session_factory,
        provider,
        monotonic=_SequenceClock(100.0, 112.5),
    )

    outcome = _run(controller, document_id, digest, estimated_seconds=600.0)

    usage = _usage_for_job(session_factory, outcome.job_id)
    assert outcome.state == "COMPLETED"
    assert outcome.estimated_usd == Decimal("0.1332")
    assert outcome.actual_usd == Decimal("0.002775")
    assert len(usage) == 1
    assert usage[0].actual_seconds == Decimal("12.500")
    assert usage[0].actual_usd == Decimal("0.002775")


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("unavailable", "PROVIDER_UNAVAILABLE"),
        ("unexpected", "PROVIDER_ERROR"),
        ("cardinality", "INVALID_BATCH_CARDINALITY"),
        ("provider_result", "INVALID_MODEL_JSON"),
        ("schema", "SCHEMA_VALIDATION_FAILED"),
    ],
)
def test_every_post_invocation_failure_reconciles_measured_usage(
    session_factory: sessionmaker[Session],
    failure_kind: str,
    expected_code: str,
) -> None:
    document_id, digest = _document(session_factory)
    settings = _settings()
    if failure_kind == "unavailable":
        provider = _RecordingProvider(raises=InferenceUnavailableError("unavailable"))
    elif failure_kind == "unexpected":
        provider = _RecordingProvider(raises=RuntimeError("provider implementation failed"))
    elif failure_kind == "cardinality":
        provider = _RecordingProvider(results=[])
    elif failure_kind == "provider_result":
        provider = _RecordingProvider(
            InferenceResult(
                ok=False,
                metadata=_metadata(settings),
                error=InferenceFailure(code="INVALID_MODEL_JSON", message="bad json"),
            )
        )
    else:
        provider = _RecordingProvider(
            InferenceResult(
                ok=True,
                metadata=_metadata(settings),
                output={"document_id": str(document_id), "boreholes": "invalid"},
            )
        )

    key = f"key-{uuid4()}"
    controller = _controller(
        session_factory,
        provider,
        monotonic=_SequenceClock(10.0, 14.25),
    )
    with unit_of_work(session_factory) as session:
        before = BudgetRepository(session).position(TERMINAL_STATES)

    # Deliberately not settled here. This test asserts the reservation was released
    # by reconciliation, and a cleanup running before `after` is measured would
    # settle an unreleased job and make that assertion pass regardless. Cross-test
    # hygiene is the truncation fixture's job, not this test's.
    outcome = _run(
        controller,
        document_id,
        digest,
        idempotency_key=key,
        estimated_seconds=600.0,
    )

    usage = _usage_for_job(session_factory, outcome.job_id)
    with unit_of_work(session_factory) as session:
        after = BudgetRepository(session).position(TERMINAL_STATES)
    expected_actual_usd = Decimal("0.0009435")
    assert outcome.state == "FAILED"
    assert outcome.error_code == expected_code
    assert outcome.actual_usd == expected_actual_usd
    assert len(usage) == 1
    assert usage[0].actual_seconds == Decimal("4.250")
    assert abs(usage[0].actual_usd - expected_actual_usd) <= Decimal("0.0000005")
    assert after.reserved_usd == before.reserved_usd


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("provider", "modal"),
        ("model_id", "different-model"),
        ("model_revision", "different-revision"),
        ("prompt_version", "v-wrong"),
        ("preprocess_version", "v-wrong"),
    ],
)
def test_result_metadata_must_match_authorized_cache_identity(
    session_factory: sessionmaker[Session],
    field: str,
    wrong_value: str,
) -> None:
    document_id, digest = _document(session_factory)
    settings = _settings()
    metadata = replace(_metadata(settings), **{field: wrong_value})
    provider = _RecordingProvider(
        InferenceResult(
            ok=True,
            metadata=metadata,
            output=_valid_output(document_id),
        )
    )
    controller = _controller(session_factory, provider)

    outcome = _run(controller, document_id, digest)

    assert outcome.state == "FAILED"
    assert outcome.error_code == "RESULT_METADATA_MISMATCH"
    with unit_of_work(session_factory) as session:
        assert CacheRepository(session).get(controller.cache_key_for(digest, "f" * 64)) is None


@pytest.mark.parametrize("invalid_identity", ["extraction", "evidence"])
def test_document_provenance_must_match_before_completion_or_caching(
    session_factory: sessionmaker[Session],
    invalid_identity: str,
) -> None:
    document_id, digest = _document(session_factory)
    settings = _settings()
    output = (
        _valid_output("different-document")
        if invalid_identity == "extraction"
        else _output_with_evidence(document_id, "different-document")
    )
    provider = _RecordingProvider(
        InferenceResult(ok=True, metadata=_metadata(settings), output=output)
    )
    controller = _controller(session_factory, provider)

    outcome = _run(controller, document_id, digest)

    assert outcome.state == "FAILED"
    assert outcome.error_code == "DOCUMENT_PROVENANCE_MISMATCH"
    with unit_of_work(session_factory) as session:
        assert CacheRepository(session).get(controller.cache_key_for(digest, "f" * 64)) is None
