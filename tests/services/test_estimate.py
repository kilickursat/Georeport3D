"""An estimate is what a user is asked to agree to, so it must not overstate certainty."""

from __future__ import annotations

from decimal import Decimal

import pytest

from document.base import ParsedDocument, ParsedFigure, ParsedPage
from document.inventory import build_inventory
from georeport3d.config import (
    CANONICAL_CACHE_KEY_FIELDS,
    BudgetPolicy,
    CachePolicy,
    LimitsPolicy,
    ModalPolicy,
    Policy,
)
from georeport3d.services.budget import profile_for
from georeport3d.services.estimate import (
    UNCALIBRATED_SECONDS_PER_REGION,
    estimate_workload,
)


def _price(profile_name: str = "L40S"):
    """The same arithmetic the controller uses, without needing a database."""
    profile = profile_for(profile_name)

    def price_usd(seconds: float) -> Decimal:
        return Decimal(str(seconds)) * Decimal(str(profile.usd_per_hour)) / Decimal(3600)

    return price_usd


def _policy(job_cap: float = 5.0, confirm_above: float = 1.0, max_pages: int = 100) -> Policy:
    return Policy(
        budget=BudgetPolicy(
            global_usd=230.0,
            default_job_cap_usd=job_cap,
            require_confirmation_above_usd=confirm_above,
            hard_stop_usd=220.0,
        ),
        limits=LimitsPolicy(
            max_file_mb=250,
            max_pages=500,
            max_ai_pages_per_job=max_pages,
            max_concurrent_gpu_jobs=1,
        ),
        cache=CachePolicy(enabled=True, key_fields=list(CANONICAL_CACHE_KEY_FIELDS)),
        modal=ModalPolicy(),
    )


def _inventory(regions: int, pages: int = 1):
    """A document carrying `regions` routed candidates."""
    per_page = [regions // pages + (1 if index < regions % pages else 0) for index in range(pages)]
    parsed = ParsedDocument(
        source_format="pdf",
        pages=tuple(
            ParsedPage(
                page_number=index + 1,
                text="Borehole log",
                figures=tuple(
                    ParsedFigure(
                        page_number=index + 1,
                        kind="figure",
                        bbox=(0.0, 0.0, 1.0, 1.0),
                        caption=f"Borehole log BH-{index}-{n}",
                    )
                    for n in range(count)
                ),
            )
            for index, count in enumerate(per_page)
        ),
    )
    return build_inventory("doc-1", "a" * 64, parsed)


def test_an_estimate_says_it_is_not_calibrated() -> None:
    """No inference has ever run on this stack, so the duration is an assumption.

    A caller that cannot tell an assumption from a measurement will treat the first
    as the second, which is how an uncalibrated number becomes a quoted price.
    """
    estimate = estimate_workload(_inventory(3), _policy(), _price())

    assert estimate.calibrated is False
    assert estimate.seconds_per_region == UNCALIBRATED_SECONDS_PER_REGION


def test_unknown_cache_hits_are_none_rather_than_zero() -> None:
    """Zero would read as "nothing is cached" and overstate the cost.

    Counting hits needs a content hash per figure, which needs the render-and-crop
    pipeline that does not exist yet.
    """
    assert estimate_workload(_inventory(3), _policy(), _price()).cache_hits is None


def test_cost_follows_the_regions_that_would_be_sent() -> None:
    estimate = estimate_workload(_inventory(4), _policy(), _price())

    assert estimate.candidate_count == 4
    assert estimate.billable_count == 4
    assert estimate.estimated_seconds == 4 * UNCALIBRATED_SECONDS_PER_REGION
    assert estimate.estimated_usd == _price()(4 * UNCALIBRATED_SECONDS_PER_REGION)


def test_an_empty_document_costs_nothing_and_needs_no_confirmation() -> None:
    estimate = estimate_workload(_inventory(0), _policy(), _price())

    assert estimate.candidate_count == 0
    assert estimate.estimated_usd == Decimal(0)
    assert estimate.requires_confirmation is False


def test_a_document_over_the_job_limit_is_reported_not_silently_truncated() -> None:
    """Pricing a partial run without saying so would quote for less than was asked."""
    estimate = estimate_workload(_inventory(12, pages=4), _policy(max_pages=5), _price())

    assert estimate.candidate_count == 12
    assert estimate.billable_count == 5
    assert estimate.exceeds_page_limit is True


@pytest.mark.parametrize(
    ("regions", "confirm_above", "expected"),
    [(1, 1.0, False), (60, 1.0, True), (60, 100.0, False)],
)
def test_confirmation_tracks_the_policy_threshold(
    regions: int, confirm_above: float, expected: bool
) -> None:
    estimate = estimate_workload(
        _inventory(regions), _policy(confirm_above=confirm_above), _price()
    )

    assert estimate.requires_confirmation is expected


def test_money_is_rendered_as_a_string_so_no_float_rounds_it() -> None:
    """JSON has one number type, and it is binary floating point.

    Serialising a Decimal through it is how an exact amount stops being exact.
    """
    response = estimate_workload(_inventory(7), _policy(), _price()).as_response()

    assert isinstance(response["estimated_usd"], str)
    assert Decimal(response["estimated_usd"]) == _price()(7 * UNCALIBRATED_SECONDS_PER_REGION)


def test_the_estimate_is_priced_at_the_deployed_gpu_rate() -> None:
    """An L4 estimate for L40S work would understate the price by 59%."""
    regions = 5
    l4 = estimate_workload(_inventory(regions), _policy(), _price("L4"))
    l40s = estimate_workload(_inventory(regions), _policy(), _price("L40S"))

    assert l40s.estimated_usd > l4.estimated_usd
    assert l40s.estimated_seconds == l4.estimated_seconds
