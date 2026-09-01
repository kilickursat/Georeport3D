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

import time
from collections.abc import Callable
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
    InferenceMetadata,
    InferenceProvider,
    InferenceRequest,
    InferenceResult,
    InferenceUnavailableError,
)
from georeport3d.services.budget import L4, BudgetLedger, GPUProfile
from georeport3d.services.cache import CacheKeyParts, make_cache_key
from georeport3d.services.job_state import (
    GPU_SLOT_STATES,
    TERMINAL_STATES,
    JobState,
    StaleJobState,
    validate_transition,
)

# Which terminal state a refusal settles in. Budget refusals are their own state so
# cost governance can count them; the rest are ordinary rejections.
_REFUSAL_STATES: dict[str, JobState] = {
    "JOB_CAP_EXCEEDED": "BUDGET_EXCEEDED",
    "BUDGET_EXHAUSTED": "BUDGET_EXCEEDED",
    "GPU_CONCURRENCY_LIMIT": "REJECTED",
    "STALE_JOB_STATE": "REJECTED",
    "CONFIRMATION_REQUIRED": "REJECTED",
}


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


_SECONDS_PER_HOUR = Decimal(3600)


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
        # Injected so a test can state elapsed time exactly, and monotonic so a
        # clock adjustment during a long call cannot produce a negative duration
        # that would under-bill the budget.
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessions = session_factory
        self._provider = provider
        self._policy = policy
        self._settings = settings
        self._ledger = ledger
        self._profile = profile
        self._monotonic = monotonic

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

    def price_usd(self, seconds: float) -> Decimal:
        """Price a duration at the profile's rate, in exact decimal arithmetic.

        Deliberately not `BudgetLedger.estimate`, which returns a float. Binary
        floating point turns 4.25 seconds at $0.7992/hour into
        0.0009435000000000001 instead of 0.0009435, and that error then travels into
        a Numeric column, a comparison against a budget ceiling, and a sum over every
        job. The profile still owns the rate; only the arithmetic moves.
        """
        return _decimal(seconds) * _decimal(self._profile.usd_per_hour) / _SECONDS_PER_HOUR

    def estimate_usd(self, estimated_seconds: float) -> Decimal:
        """Price an estimate, carried as an exact decimal."""
        return self.price_usd(estimated_seconds)

    # -- admission ------------------------------------------------------------

    def _admit(self, session: Session, job_id: UUID, estimate: Decimal) -> str | None:
        """Reserve budget and a GPU slot, or return why it was refused.

        Every decision and the reservation happen inside one serialized database
        critical section, so two processes cannot both read an affordable position
        and then both reserve against it.
        """
        decision = BudgetRepository(session).admit_and_reserve(
            job_id=job_id,
            expected_state="CACHE_LOOKUP",
            estimate_usd=estimate,
            job_cap_usd=_decimal(self._policy.budget.default_job_cap_usd),
            ceiling_usd=min(
                _decimal(self._policy.budget.global_usd),
                _decimal(self._policy.budget.hard_stop_usd),
            ),
            max_concurrent_gpu_jobs=self._policy.limits.max_concurrent_gpu_jobs,
            gpu_slot_states=GPU_SLOT_STATES,
            terminal_states=TERMINAL_STATES,
        )
        return None if decision.authorized else decision.reason

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
        confirmed: bool = False,
    ) -> JobOutcome:
        """Take one unit of work from queued to settled.

        `confirmed` is the human decision that policy asks for above
        `require_confirmation_above_usd`. It defaults to False so a caller that has
        not thought about it cannot spend past the threshold by omission.
        """
        cache_key = self.cache_key_for(document_sha256, figure_sha256)
        estimate = self.estimate_usd(estimated_seconds)

        decision = self._open(
            document_id=document_id,
            idempotency_key=idempotency_key,
            cache_key=cache_key,
            estimate=estimate,
            confirmed=confirmed,
        )
        if decision.settled is not None:
            return decision.settled

        job_id = decision.job_id
        self._advance(job_id, "GPU_AUTHORIZED", "GPU_RUNNING")

        request = InferenceRequest(
            messages=messages,
            max_tokens=max_tokens,
            prompt_version=self._settings.prompt_version,
            preprocess_version=self._settings.preprocess_version,
            model_revision=self._settings.model_revision,
        )

        # Outside any transaction: this is a remote call that may start a container,
        # and holding a transaction across it would pin a connection for minutes.
        #
        # The clock is read once on each side of the call, including when it raises.
        # What the budget must record is how long a GPU actually ran, which is not
        # the estimate the job was admitted on: a job estimated at ten minutes that
        # fails after four seconds has spent four seconds.
        started = self._monotonic()
        results: list[InferenceResult] | None = None
        failure: str | None = None
        try:
            results = list(self._provider.extract_batch([request]))
        except InferenceUnavailableError:
            failure = "PROVIDER_UNAVAILABLE"
        except Exception:  # noqa: BLE001 - a provider defect must still reconcile
            # The reservation is live at this point. Letting an unexpected exception
            # escape would leave it counted against the budget forever, so the code
            # is deliberately stable and carries no provider detail.
            failure = "PROVIDER_ERROR"
        finally:
            elapsed = max(0.0, self._monotonic() - started)

        if failure is not None:
            return self._reconcile_failure(job_id, "GPU_RUNNING", failure, estimate, elapsed)
        assert results is not None
        if len(results) != 1:
            return self._reconcile_failure(
                job_id, "GPU_RUNNING", "INVALID_BATCH_CARDINALITY", estimate, elapsed
            )

        return self._settle(
            job_id=job_id,
            result=results[0],
            cache_key=cache_key,
            document_id=document_id,
            document_sha256=document_sha256,
            figure_sha256=figure_sha256,
            estimate=estimate,
            elapsed_seconds=elapsed,
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
        confirmed: bool,
    ) -> _Opening:
        """Create or recover the job, then look in the cache before refusing anything.

        The lookup comes first on purpose. A cache hit costs nothing, so refusing it
        for want of budget, confirmation, or a GPU slot would deny an answer that is
        already paid for and sitting in the database. Only a miss can cost money, and
        only a miss is subject to admission.
        """
        with unit_of_work(self._sessions) as session:
            jobs = InferenceJobRepository(session)
            job, created = jobs.create(
                document_id=document_id,
                idempotency_key=idempotency_key,
                cache_key=cache_key,
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

            if not created:
                # Any existing job for this identity - settled or still running -
                # reports its persisted status. Restarting a live job would run the
                # same work twice; reviving a settled one would reserve twice.
                cached = CacheRepository(session).get(cache_key)
                return self._Opening(
                    job_id=job.id,
                    settled=JobOutcome(
                        job_id=job.id,
                        state=job.state,  # type: ignore[arg-type]
                        cache_hit=job.state in TERMINAL_STATES and cached is not None,
                        estimated_usd=Decimal(job.estimated_usd),
                        output=cached if job.state == "COMPLETED" else None,
                        error_code=job.error_code,
                    ),
                )

            validate_transition(job.state, "PRECHECKING")
            jobs.set_state(job.id, "PRECHECKING")
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

            # A miss above the threshold stops here, before any reservation exists,
            # so an unconfirmed expensive request cannot hold budget while it waits.
            if not confirmed and self.requires_confirmation(estimate):
                return self._Opening(
                    job_id=job.id,
                    settled=self._refuse(jobs, job.id, "CONFIRMATION_REQUIRED", estimate),
                )

            refusal = self._admit(session, job.id, estimate)
            if refusal is not None:
                return self._Opening(
                    job_id=job.id,
                    settled=self._refuse(jobs, job.id, refusal, estimate),
                )
            return self._Opening(job_id=job.id, settled=None)

    def _refuse(
        self,
        jobs: InferenceJobRepository,
        job_id: UUID,
        error_code: str,
        estimate: Decimal,
    ) -> JobOutcome:
        """Settle a job that never reached a GPU, holding no reservation."""
        state = _REFUSAL_STATES[error_code]
        validate_transition("CACHE_LOOKUP", state)
        jobs.compare_and_set_state(
            job_id,
            expected_state="CACHE_LOOKUP",
            target_state=state,
            error_code=error_code,
            reserved_usd=Decimal(0),
        )
        return JobOutcome(
            job_id=job_id,
            state=state,
            cache_hit=False,
            estimated_usd=estimate,
            error_code=error_code,
        )

    def _advance(self, job_id: UUID, current: JobState, target: JobState) -> None:
        """Move a job forward only if it is still where the caller left it.

        A blind write here would let a slow caller resurrect a job an operator has
        since cancelled, putting a terminal job back on the path to a GPU.
        """
        with unit_of_work(self._sessions) as session:
            validate_transition(current, target)
            moved = InferenceJobRepository(session).compare_and_set_state(
                job_id, expected_state=current, target_state=target
            )
        if not moved:
            raise StaleJobState(f"job is no longer in {current}")

    def _metadata_matches(self, metadata: InferenceMetadata) -> bool:
        """Whether the result came from the identity the job was authorized for.

        The cache key is derived from these fields. A result produced under a
        different model, revision, or prompt would be stored under a key that does
        not describe it, and then served for work it never did.
        """
        expected_provider = "modal" if self._settings.inference_provider == "modal" else "mock"
        return (
            metadata.provider == expected_provider
            and metadata.model_id == self._settings.model_id
            and metadata.model_revision == self._settings.model_revision
            and metadata.prompt_version == self._settings.prompt_version
            and metadata.preprocess_version == self._settings.preprocess_version
        )

    @staticmethod
    def _provenance_matches(extraction: GeotechnicalExtraction, document_id: UUID) -> bool:
        """Whether the extraction and every citation in it name this document.

        A model can return a well-formed extraction about the wrong document. Storing
        it would attach another document's geology to this one, with citations that
        look valid and point somewhere else.
        """
        expected = str(document_id)
        if extraction.document_id != expected:
            return False
        for borehole in extraction.boreholes:
            citations = list(borehole.evidence)
            for interval in borehole.intervals:
                citations.extend(interval.evidence)
            if any(evidence.document_id != expected for evidence in citations):
                return False
        return True

    def _settle(
        self,
        *,
        job_id: UUID,
        result: InferenceResult,
        cache_key: str,
        document_id: UUID,
        document_sha256: str,
        figure_sha256: str,
        estimate: Decimal,
        elapsed_seconds: float,
    ) -> JobOutcome:
        """Validate, persist, and reconcile in one transaction."""
        self._advance(job_id, "GPU_RUNNING", "VALIDATING")

        if not result.ok or result.output is None:
            code = result.error.code if result.error is not None else "INFERENCE_FAILED"
            return self._reconcile_failure(job_id, "VALIDATING", code, estimate, elapsed_seconds)

        if not self._metadata_matches(result.metadata):
            return self._reconcile_failure(
                job_id, "VALIDATING", "RESULT_METADATA_MISMATCH", estimate, elapsed_seconds
            )

        try:
            extraction = GeotechnicalExtraction.model_validate(result.output)
        except Exception:  # noqa: BLE001 - any validation failure is refused alike
            # docs/10: never return a successful extraction when validation fails.
            return self._reconcile_failure(
                job_id, "VALIDATING", "SCHEMA_VALIDATION_FAILED", estimate, elapsed_seconds
            )

        if not self._provenance_matches(extraction, document_id):
            return self._reconcile_failure(
                job_id, "VALIDATING", "DOCUMENT_PROVENANCE_MISMATCH", estimate, elapsed_seconds
            )

        actual_usd = self.price_usd(elapsed_seconds)
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
                actual_seconds=elapsed_seconds,
                actual_usd=actual_usd,
            )

            validate_transition("PERSISTING", "COMPLETED")
            # Settling releases the reservation: from here the job is accounted for
            # by its measured usage, not by what it was expected to cost.
            jobs.compare_and_set_state(
                job_id,
                expected_state="PERSISTING",
                target_state="COMPLETED",
                reserved_usd=Decimal(0),
            )

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
        current: JobState,
        error_code: str,
        estimate: Decimal,
        elapsed_seconds: float,
    ) -> JobOutcome:
        """Record what a failed attempt actually cost before settling it.

        Every path after the provider call was invoked arrives here, including an
        unexpected exception. Two things must happen together and exactly once: the
        measured spend is recorded, because a GPU that ran consumed time whatever it
        returned, and the reservation is released by settling the job. Skipping the
        first lets the same budget be spent twice; skipping the second leaves a
        reservation counted against the budget forever.
        """
        actual_usd = self.price_usd(elapsed_seconds)
        with unit_of_work(self._sessions) as session:
            UsageRepository(session).record(
                inference_job_id=job_id,
                gpu_profile=self._profile.name,
                actual_seconds=elapsed_seconds,
                actual_usd=actual_usd,
            )
            validate_transition(current, "FAILED")
            InferenceJobRepository(session).compare_and_set_state(
                job_id,
                expected_state=current,
                target_state="FAILED",
                error_code=error_code,
                reserved_usd=Decimal(0),
            )

        return JobOutcome(
            job_id=job_id,
            state="FAILED",
            cache_hit=False,
            estimated_usd=estimate,
            actual_usd=actual_usd,
            error_code=error_code,
        )
