"""Guards for cost defects that were found by luck rather than by a test.

Each case here corresponds to a bug that reached `main` and was caught only because
some unrelated assertion happened to trip over it. They are cheap, they need no
database, and they fail loudly if the same mistake returns.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from georeport3d.services.budget import L4, L40S, PROFILES, GPUProfile, profile_for


@pytest.mark.parametrize(
    ("name", "usd_per_second"),
    [("L4", "0.000222"), ("L40S", "0.000542")],
)
def test_published_modal_rates_are_carried_exactly(name: str, usd_per_second: str) -> None:
    """The rates are quoted per second by Modal and stored per hour.

    Checked against Modal's published pricing on 2026-09-01. If a rate is edited, this
    is the test that should force the edit to be deliberate rather than incidental.
    """
    profile = profile_for(name)
    assert Decimal(str(profile.usd_per_hour)) == Decimal(usd_per_second) * 3600


def test_an_unpriced_gpu_is_refused_rather_than_defaulted() -> None:
    """A silent fallback to L4 would bill an L40S at 41% of its real cost.

    That error is invisible until the budget has already been overspent, so an
    unknown GPU has to fail at the point of configuration instead.
    """
    with pytest.raises(ValueError, match="no billing rate"):
        profile_for("H100")


def test_every_configurable_gpu_has_a_rate() -> None:
    """The policy's GPU choices and the billing table must not drift apart.

    `ModalPolicy.gpu` constrains what can be deployed; `PROFILES` decides what can be
    billed. A GPU in the first without the second deploys and then cannot be priced.
    """
    from typing import get_args

    from georeport3d.config import ModalPolicy

    configurable = set(get_args(ModalPolicy.model_fields["gpu"].annotation))
    assert configurable <= set(PROFILES), f"unpriced GPUs: {configurable - set(PROFILES)}"


@pytest.mark.parametrize("profile", [L4, L40S])
@pytest.mark.parametrize("seconds", [0.0, 4.25, 12.5, 30.0, 600.0, 3600.0, 7.7])
def test_pricing_is_exact_decimal_not_binary_float(
    profile: GPUProfile, seconds: float
) -> None:
    """Money must equal the decimal product, to the last digit.

    Measured: at the L4 rate, 4.25 seconds priced through float arithmetic gives
    0.0009435000000000001 rather than 0.0009435. That value then reaches a Numeric
    column, a comparison against the budget ceiling, and a sum over every job, so the
    error does not stay where it was made. Asserted over several durations rather
    than the one that happened to be caught.
    """
    from georeport3d.services.controller import JobController

    expected = Decimal(str(seconds)) * Decimal(str(profile.usd_per_hour)) / Decimal(3600)
    priced = JobController.price_usd(_pricer(profile), seconds)

    assert priced == expected
    assert isinstance(priced, Decimal)
    # The float path is what this exists to exclude; it must not merely be close.
    assert str(priced) == str(expected)


class _pricer:
    """The minimum a bound `price_usd` needs, so no database is involved."""

    def __init__(self, profile: GPUProfile) -> None:
        self._profile = profile
