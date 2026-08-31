"""The controller's ordering is the cost control, so each guard is asserted."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
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

VALID_OUTPUT: dict[str, object] = {
    "document_id": "doc-1",
    "boreholes": [],
    "contacts": [],
    "sections": [],
    "notes": [],
    "extraction_confidence": 0.0,
}


class _RecordingProvider:
    """Records every call so 'never reached the GPU' can be asserted directly."""

    def __init__(self, result: InferenceResult | None = None, raises: Exception | None = None):
        self.calls: list[list[InferenceRequest]] = []
        self._result = result
        self._raises = raises

    def extract_batch(self, requests):  # noqa: ANN001, ANN201 - matches the Protocol
        self.calls.append(list(requests))
        if self._raises is not None:
            raise self._raises
        assert self._result is not None
        return [self._result]


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


def _policy(global_usd: float = 230.0, hard_stop: float = 220.0, job_cap: float = 5.0) -> Policy:
    return Policy(
        budget=BudgetPolicy(
            global_usd=global_usd,
            default_job_cap_usd=job_cap,
            require_confirmation_above_usd=1.0,
            hard_stop_usd=hard_stop,
        ),
        limits=LimitsPolicy(
            max_file_mb=250, max_pages=500, max_ai_pages_per_job=100, max_concurrent_gpu_jobs=1
        ),
        cache=CachePolicy(enabled=True, key_fields=list(CANONICAL_CACHE_KEY_FIELDS)),
        modal=ModalPolicy(),
    )


def _controller(
    session_factory: sessionmaker[Session],
    provider: _RecordingProvider,
    policy: Policy | None = None,
) -> JobController:
    return JobController(
        session_factory=session_factory,
        provider=provider,
        policy=policy or _policy(),
        settings=_settings(),
        ledger=BudgetLedger(),
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


def test_a_miss_runs_the_pipeline_and_records_what_it_spent(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, digest = _document(session_factory)
    settings = _settings()
    provider = _RecordingProvider(
        InferenceResult(ok=True, metadata=_metadata(settings), output=VALID_OUTPUT)
    )
    controller = _controller(session_factory, provider)

    outcome = _run(controller, document_id, digest)

    assert outcome.state == "COMPLETED"
    assert outcome.cache_hit is False
    assert outcome.output == VALID_OUTPUT
    assert outcome.actual_usd is not None and outcome.actual_usd > 0
    assert len(provider.calls) == 1

    with unit_of_work(session_factory) as session:
        key = controller.cache_key_for(digest, "f" * 64)
        assert CacheRepository(session).get(key) == VALID_OUTPUT
        # The reservation is released by settling, leaving only measured spend.
        position = BudgetRepository(session).position(TERMINAL_STATES)
        assert position.settled_usd >= outcome.actual_usd


def test_a_second_request_hits_the_cache_and_never_reaches_the_provider(
    session_factory: sessionmaker[Session],
) -> None:
    document_id, digest = _document(session_factory)
    settings = _settings()
    first = _RecordingProvider(
        InferenceResult(ok=True, metadata=_metadata(settings), output=VALID_OUTPUT)
    )
    _run(_controller(session_factory, first), document_id, digest)

    # A provider that fails if touched proves the second run costs nothing.
    second = _RecordingProvider(raises=AssertionError("provider must not be called"))
    outcome = _run(_controller(session_factory, second), document_id, digest)

    assert outcome.state == "COMPLETED"
    assert outcome.cache_hit is True
    assert outcome.actual_usd == Decimal(0)
    assert outcome.output == VALID_OUTPUT
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
    controller = _controller(session_factory, provider)
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
        InferenceResult(ok=True, metadata=_metadata(settings), output=VALID_OUTPUT)
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
