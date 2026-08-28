import pytest

from georeport3d.services.budget import BudgetLedger, GPUProfile

INVALID_NUMBERS = (
    pytest.param(-1.0, id="negative"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="positive-infinity"),
    pytest.param(float("-inf"), id="negative-infinity"),
)


def test_authorization_reserves_available_budget() -> None:
    ledger = BudgetLedger(global_budget_usd=10, hard_stop_usd=5)
    first = ledger.authorize("job-1", estimated_seconds=18000, job_cap_usd=5)
    assert round(first.estimated_usd, 3) == 3.996
    with pytest.raises(RuntimeError, match="budget"):
        ledger.authorize("job-2", estimated_seconds=18000, job_cap_usd=5)


def test_record_releases_unused_reservation() -> None:
    ledger = BudgetLedger(global_budget_usd=10, hard_stop_usd=9)
    ledger.authorize("job-1", estimated_seconds=3600, job_cap_usd=2)
    actual = ledger.record("job-1", actual_seconds=1800)
    assert round(actual, 4) == 0.3996
    assert ledger.reserved_usd == 0
    assert ledger.spent_usd == actual


@pytest.mark.parametrize(
    "field",
    ("global_budget_usd", "hard_stop_usd", "spent_usd"),
)
@pytest.mark.parametrize("value", INVALID_NUMBERS)
def test_ledger_rejects_invalid_constructor_numbers(field: str, value: float) -> None:
    values = {
        "global_budget_usd": 10.0,
        "hard_stop_usd": 9.0,
        "spent_usd": 0.0,
    }
    values[field] = value
    with pytest.raises(ValueError):
        BudgetLedger(**values)


def test_ledger_rejects_hard_stop_above_global_budget() -> None:
    with pytest.raises(ValueError):
        BudgetLedger(global_budget_usd=10, hard_stop_usd=11)


@pytest.mark.parametrize(
    "field",
    ("global_budget_usd", "hard_stop_usd", "spent_usd"),
)
def test_budget_state_is_read_only(field: str) -> None:
    ledger = BudgetLedger(global_budget_usd=10, hard_stop_usd=9, spent_usd=1)
    with pytest.raises(AttributeError):
        setattr(ledger, field, 100.0)


@pytest.mark.parametrize("field", ("estimated_seconds", "job_cap_usd"))
@pytest.mark.parametrize("value", INVALID_NUMBERS)
def test_authorize_rejects_invalid_numbers(field: str, value: float) -> None:
    ledger = BudgetLedger(global_budget_usd=10, hard_stop_usd=9)
    values = {"estimated_seconds": 3600.0, "job_cap_usd": 1.0}
    values[field] = value
    with pytest.raises(ValueError):
        ledger.authorize("job", **values)
    assert ledger.reserved_usd == 0
    assert ledger.spent_usd == 0


@pytest.mark.parametrize("value", INVALID_NUMBERS)
def test_record_validation_preserves_reservation_and_spend(value: float) -> None:
    ledger = BudgetLedger(global_budget_usd=10, hard_stop_usd=9, spent_usd=1)
    ledger.authorize("job", estimated_seconds=3600, job_cap_usd=1)
    reserved_before = ledger.reserved_usd
    spent_before = ledger.spent_usd

    with pytest.raises(ValueError):
        ledger.record("job", actual_seconds=value)

    assert ledger.reserved_usd == reserved_before
    assert ledger.spent_usd == spent_before


@pytest.mark.parametrize("value", INVALID_NUMBERS)
def test_gpu_profile_rejects_invalid_hourly_rate(value: float) -> None:
    with pytest.raises(ValueError):
        GPUProfile("custom", value)


def test_record_keeps_finite_actual_overrun() -> None:
    ledger = BudgetLedger(global_budget_usd=10, hard_stop_usd=9)
    reservation = ledger.authorize("job", estimated_seconds=1, job_cap_usd=1)

    actual = ledger.record("job", actual_seconds=3600)

    assert actual == pytest.approx(0.7992)
    assert actual > reservation.estimated_usd
    assert ledger.reserved_usd == 0
    assert ledger.spent_usd == actual
