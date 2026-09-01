"""Predict what an extraction would cost, before anything is authorized.

This is the number a user is asked to confirm, so the honest thing is for it to say
what it does not know. Two of its inputs are not available yet, and both are marked
rather than guessed:

`cache_hits` needs a content hash per figure, which needs the render-and-crop
pipeline that `docs/10_API_AND_JOB_STATE.md` lists as a prerequisite. Until then the
count is `None` — not zero, which would read as "nothing is cached" and quietly
overstate the cost.

`calibrated` is False until a real inference has been measured on the deployed GPU
(PLAN.md step 15). Until then the per-region duration is an assumption, and a caller
must be able to tell an assumption from a measurement.

Nothing here touches a provider or a GPU. Producing an estimate is free, which is the
point: a user has to be able to see the price before agreeing to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from document.inventory import DocumentInventory
from georeport3d.config import Policy

# Deliberately generous, and deliberately not derived from anything. No inference has
# ever run on this stack, so any figure here is an assumption; a high one errs toward
# refusing work that would have been affordable, and a low one errs toward admitting
# work the budget cannot cover. Only the first failure is recoverable, so the estimate
# rounds against the user rather than against the budget. Step 15 replaces this with a
# measured value and flips `calibrated`.
UNCALIBRATED_SECONDS_PER_REGION = 60.0


@dataclass(frozen=True)
class WorkloadEstimate:
    """What one document would cost to extract, and how much of that is known."""

    page_count: int
    candidate_count: int
    billable_count: int
    estimated_seconds: float
    estimated_usd: Decimal
    requires_confirmation: bool
    calibrated: bool
    cache_hits: int | None
    exceeds_page_limit: bool
    seconds_per_region: float

    def as_response(self) -> dict[str, object]:
        """Render for the API, with money as a string so no float rounds it."""
        return {
            "page_count": self.page_count,
            "candidate_count": self.candidate_count,
            "billable_count": self.billable_count,
            "estimated_seconds": self.estimated_seconds,
            "estimated_usd": str(self.estimated_usd),
            "requires_confirmation": self.requires_confirmation,
            "calibrated": self.calibrated,
            "cache_hits": self.cache_hits,
            "exceeds_page_limit": self.exceeds_page_limit,
            "seconds_per_region": self.seconds_per_region,
        }


def estimate_workload(
    inventory: DocumentInventory,
    policy: Policy,
    price_usd: object,
    *,
    seconds_per_region: float = UNCALIBRATED_SECONDS_PER_REGION,
    cache_hits: int | None = None,
    calibrated: bool = False,
) -> WorkloadEstimate:
    """Price the regions this document would send to a vision model.

    `price_usd` is the controller's pricing callable, so the estimate and the
    reservation that later admits the job are derived from the same rate. Passing it
    in rather than importing a profile keeps a single source for what a GPU second
    costs; two independent copies would drift the moment one GPU changed.
    """
    candidates = inventory.candidates()
    candidate_count = len(candidates)

    # The cap is per job, so a document with more candidates than the limit is
    # reported as exceeding it rather than silently priced for a partial run.
    limit = policy.limits.max_ai_pages_per_job
    billable_count = min(candidate_count, limit)

    estimated_seconds = billable_count * seconds_per_region
    estimated_usd = price_usd(estimated_seconds)  # type: ignore[operator]
    threshold = Decimal(str(policy.budget.require_confirmation_above_usd))

    return WorkloadEstimate(
        page_count=inventory.page_count,
        candidate_count=candidate_count,
        billable_count=billable_count,
        estimated_seconds=estimated_seconds,
        estimated_usd=estimated_usd,
        requires_confirmation=estimated_usd > threshold,
        calibrated=calibrated,
        cache_hits=cache_hits,
        exceeds_page_limit=candidate_count > limit,
        seconds_per_region=seconds_per_region,
    )


__all__ = [
    "UNCALIBRATED_SECONDS_PER_REGION",
    "WorkloadEstimate",
    "estimate_workload",
]
