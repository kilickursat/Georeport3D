"""The job controller that orders every step before and after a GPU call.

The enforced order is cache, estimate, reserve, infer, validate, persist,
reconcile. It exists because each step protects the one after it: the cache stops
work that has already been done, the estimate and reservation stop work the budget
cannot afford, validation stops a bad result from being stored, and reconciliation
records what was actually spent so the next estimate is admitted against the truth.

The provider call happens outside any transaction. It is a network call to a
container that may take minutes to start, and holding a database transaction open
across it would pin a connection and lock rows for the duration.

Budget admission reads durable rows rather than process memory. The in-memory
ledger keeps its role as the rate calculator, because it owns the GPU pricing, but
it is no longer the accountant: a restart used to reset all recorded spend to zero
and let the budget be spent again.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from georeport3d.config import Policy, Settings
from georeport3d.db.repositories import (
    BudgetRepository,
    CacheRepository,
    InferenceJobRepository,
    UsageRepository,
)
from georeport3d.db.session import unit_of_work
from georeport3d.domain.models import GeotechnicalExtraction
from georeport3d.inference.base import (
    InferenceProvider,
    InferenceRequest,
    InferenceResult,
    InferenceUnavailableError,
)
from georeport3d.services.budget import L4, BudgetLedger, GPUProfile
from georeport3d.services.cache import CacheKeyParts, make_cache_key
from georeport3d.services.job_state import (
    TERMINAL_STATES,
    JobState,
    validate_transition,
)


class BudgetExceeded(RuntimeError):
    """Admission refused because the durable budget cannot cover the estimate."""


@dataclass(frozen=True)
class JobOutcome:
    """What a controller run settled on, for a caller or an API route to report."""

    job_id: UUID
    state: JobState
    cache_hit: bool
    estimated_usd: Decimal
    actual_usd: Decimal | None = None
    output: dict[str, object] | None = None
    error_code: str | None = None

    @property
    def ok(self) -> bool:
        return self.state == "COMPLETED"


def _decimal(value: float | int | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


class JobController:
    """Run one inference unit through the ordered pipeline."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        provider: InferenceProvider,
        policy: Policy,
        settings: Settings,
        ledger: BudgetLedger,
        profile: GPUProfile = L4,
    ) -> None:
        self._sessions = session_factory
        self._provider = provider
        self._policy = policy
        self._settings = settings
        self._ledger = ledger
        self._profile = profile

    # -- key derivation -------------------------------------------------------

    def cache_key_for(self, document_sha256: str, figure_sha256: str) -> str:
        """Derive the canonical key for one figure of one document."""
        return make_cache_key(
            CacheKeyParts(
                document_sha256=document_sha256,
                figure_sha256=figure_sha256,
                model_id=self._settings.model_id,
                model_revision=self._settings.model_revision,
                prompt_version=self._settings.prompt_version,
                preprocess_version=self._settings.preprocess_version,
            )
        )

    def estimate_usd(self, estimated_seconds: float) -> Decimal:
        """Price an estimate using the ledger's rate, carried as an exact decimal."""
        return _decimal(self._ledger.estimate(estimated_seconds, self._profile))

    # -- admission ------------------------------------------------------------

    def _admit(self, session: Session, estimate: Decimal) -> str | None:
        """Return a refusal reason, or None when the estimate can be afforded."""
        job_cap = _decimal(self._policy.budget.default_job_cap_usd)
        if estimate > job_cap:
            return "JOB_CAP_EXCEEDED"

        position = BudgetRepository(session).position(TERMINAL_STATES)
        ceiling = min(
            _decimal(self._policy.budget.global_usd),
            _decimal(self._policy.budget.hard_stop_usd),
        )
        if position.committed_usd + estimate > ceiling:
            return "BUDGET_EXHAUSTED"
        return None

    def requires_confirmation(self, estimate: Decimal) -> bool:
        """Whether policy wants a human to approve this spend before it starts."""
        return estimate > _decimal(self._policy.budget.require_confirmation_above_usd)

    # -- the ordered pipeline -------------------------------------------------

    def run(
        self,
        *,
        document_id: UUID,
        document_sha256: str,
        figure_sha256: str,
        messages: list[dict[str, object]],
        idempotency_key: str,
        estimated_seconds: float,
        max_tokens: int = 2500,
    ) -> JobOutcome:
        """Take one unit of work from queued to settled."""
        cache_key = self.cache_key_for(document_sha256, figure_sha256)
        estimate = self.estimate_usd(estimated_seconds)

        decision = self._open(
            document_id=document_id,
            idempotency_key=idempotency_key,
            cache_key=cache_key,
            estimate=estimate,
        )
        if decision.settled is not None:
            return decision.settled

        job_id = decision.job_id
        self._advance(job_id, "GPU_AUTHORIZED", "GPU_RUNNING")

        # Outside any transaction: this is a remote call that may start a container.
        request = InferenceRequest(
            messages=messages,
            max_tokens=max_tokens,
            prompt_version=self._settings.prompt_version,
            preprocess_version=self._settings.preprocess_version,
            model_revision=self._settings.model_revision,
        )
        try:
            results = self._provider.extract_batch([request])
        except InferenceUnavailableError:
            return self._fail(job_id, "GPU_RUNNING", "PROVIDER_UNAVAILABLE", estimate)

        if len(results) != 1:
            return self._fail(job_id, "GPU_RUNNING", "INVALID_BATCH_CARDINALITY", estimate)

        return self._settle(
            job_id=job_id,
            result=results[0],
            cache_key=cache_key,
            document_sha256=document_sha256,
            figure_sha256=figure_sha256,
            estimate=estimate,
            estimated_seconds=estimated_seconds,
        )

    # -- stages ---------------------------------------------------------------

    @dataclass(frozen=True)
    class _Opening:
        job_id: UUID
        settled: JobOutcome | None

    def _open(
        self,
        *,
        document_id: UUID,
        idempotency_key: str,
        cache_key: str,
        estimate: Decimal,
    ) -> _Opening:
        """Create or recover the job, then precheck and look in the cache."""
        with unit_of_work(self._sessions) as session:
            jobs = InferenceJobRepository(session)
            job, created = jobs.create(
                document_id=document_id,
                idempotency_key=idempotency_key,
                provider="modal" if self._settings.inference_provider == "modal" else "mock",
                model_id=self._settings.model_id,
                model_revision=self._settings.model_revision,
                prompt_version=self._settings.prompt_version,
                preprocess_version=self._settings.preprocess_version,
                estimated_usd=estimate,
                # Nothing is reserved until admission succeeds, so a refused job
                # never holds budget.
                reserved_usd=Decimal(0),
            )

            if not created and job.state in TERMINAL_STATES:
                # A replayed key for work that already settled returns that outcome
                # rather than starting a second job for the same unit.
                cached = CacheRepository(session).get(cache_key)
                return self._Opening(
                    job_id=job.id,
                    settled=JobOutcome(
                        job_id=job.id,
                        state=job.state,  # type: ignore[arg-type]
                        cache_hit=cached is not None,
                        estimated_usd=Decimal(job.estimated_usd),
                        output=cached,
                        error_code=job.error_code,
                    ),
                )

            validate_transition(job.state, "PRECHECKING")
            jobs.set_state(job.id, "PRECHECKING")

            refusal = self._admit(session, estimate)
            if refusal is not None:
                validate_transition("PRECHECKING", "BUDGET_EXCEEDED")
                jobs.set_state(job.id, "BUDGET_EXCEEDED", error_code=refusal)
                return self._Opening(
                    job_id=job.id,
                    settled=JobOutcome(
                        job_id=job.id,
                        state="BUDGET_EXCEEDED",
                        cache_hit=False,
                        estimated_usd=estimate,
                        error_code=refusal,
                    ),
                )

            validate_transition("PRECHECKING", "CACHE_LOOKUP")
            jobs.set_state(job.id, "CACHE_LOOKUP")

            cached = CacheRepository(session).get(cache_key)
            if cached is not None:
                # A hit settles the job without ever authorising a GPU, and without
                # taking a reservation, so a repeated request costs nothing.
                validate_transition("CACHE_LOOKUP", "COMPLETED")
                jobs.set_state(job.id, "COMPLETED")
                return self._Opening(
                    job_id=job.id,
                    settled=JobOutcome(
                        job_id=job.id,
                        state="COMPLETED",
                        cache_hit=True,
                        estimated_usd=estimate,
                        actual_usd=Decimal(0),
                        output=cached,
                    ),
                )

            # The reservation becomes real only here, at the last point before a GPU
            # can be reached, and it counts against the budget until the job settles.
            validate_transition("CACHE_LOOKUP", "GPU_AUTHORIZED")
            job.reserved_usd = estimate
            jobs.set_state(job.id, "GPU_AUTHORIZED")
            return self._Opening(job_id=job.id, settled=None)

    def _advance(self, job_id: UUID, current: JobState, target: JobState) -> None:
        with unit_of_work(self._sessions) as session:
            validate_transition(current, target)
            InferenceJobRepository(session).set_state(job_id, target)

    def _fail(
        self,
        job_id: UUID,
        current: JobState,
        error_code: str,
        estimate: Decimal,
    ) -> JobOutcome:
        with unit_of_work(self._sessions) as session:
            validate_transition(current, "FAILED")
            InferenceJobRepository(session).set_state(job_id, "FAILED", error_code=error_code)
        return JobOutcome(
            job_id=job_id,
            state="FAILED",
            cache_hit=False,
            estimated_usd=estimate,
            error_code=error_code,
        )

    def _settle(
        self,
        *,
        job_id: UUID,
        result: InferenceResult,
        cache_key: str,
        document_sha256: str,
        figure_sha256: str,
        estimate: Decimal,
        estimated_seconds: float,
    ) -> JobOutcome:
        """Validate, persist, and reconcile in one transaction."""
        self._advance(job_id, "GPU_RUNNING", "VALIDATING")

        if not result.ok or result.output is None:
            code = result.error.code if result.error is not None else "INFERENCE_FAILED"
            return self._reconcile_failure(job_id, code, estimate, estimated_seconds)

        try:
            GeotechnicalExtraction.model_validate(result.output)
        except Exception:  # noqa: BLE001 - any validation failure is refused alike
            # docs/10: never return a successful extraction when validation fails.
            return self._reconcile_failure(
                job_id, "SCHEMA_VALIDATION_FAILED", estimate, estimated_seconds
            )

        actual_usd = _decimal(self._ledger.estimate(estimated_seconds, self._profile))
        with unit_of_work(self._sessions) as session:
            jobs = InferenceJobRepository(session)
            validate_transition("VALIDATING", "PERSISTING")
            jobs.set_state(job_id, "PERSISTING")

            CacheRepository(session).put(
                cache_key=cache_key,
                document_sha256=document_sha256,
                figure_sha256=figure_sha256,
                model_id=self._settings.model_id,
                model_revision=self._settings.model_revision,
                prompt_version=self._settings.prompt_version,
                preprocess_version=self._settings.preprocess_version,
                result=result.output,
            )
            UsageRepository(session).record(
                inference_job_id=job_id,
                gpu_profile=self._profile.name,
                actual_seconds=estimated_seconds,
                actual_usd=actual_usd,
            )

            validate_transition("PERSISTING", "COMPLETED")
            jobs.set_state(job_id, "COMPLETED")

        return JobOutcome(
            job_id=job_id,
            state="COMPLETED",
            cache_hit=False,
            estimated_usd=estimate,
            actual_usd=actual_usd,
            output=result.output,
        )

    def _reconcile_failure(
        self,
        job_id: UUID,
        error_code: str,
        estimate: Decimal,
        estimated_seconds: float,
    ) -> JobOutcome:
        """Record what a failed attempt actually cost before settling it.

        A GPU that ran and then produced an unusable answer still consumed time, so
        the spend is recorded. Omitting it would let the same budget be spent twice.
        """
        actual_usd = _decimal(self._ledger.estimate(estimated_seconds, self._profile))
        with unit_of_work(self._sessions) as session:
            UsageRepository(session).record(
                inference_job_id=job_id,
                gpu_profile=self._profile.name,
                actual_seconds=estimated_seconds,
                actual_usd=actual_usd,
            )
            validate_transition("VALIDATING", "FAILED")
            InferenceJobRepository(session).set_state(job_id, "FAILED", error_code=error_code)

        return JobOutcome(
            job_id=job_id,
            state="FAILED",
            cache_hit=False,
            estimated_usd=estimate,
            actual_usd=actual_usd,
            error_code=error_code,
        )
