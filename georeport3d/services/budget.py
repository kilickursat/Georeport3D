from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real
from threading import Lock


def _finite_non_negative(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite non-negative number")
    numeric = float(value)
    if not isfinite(numeric) or numeric < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return numeric


@dataclass(frozen=True)
class GPUProfile:
    name: str
    usd_per_hour: float

    def __post_init__(self) -> None:
        rate = _finite_non_negative(self.usd_per_hour, "usd_per_hour")
        object.__setattr__(self, "usd_per_hour", rate)


L4 = GPUProfile("L4", 0.000222 * 3600)


@dataclass(frozen=True)
class BudgetReservation:
    job_id: str
    estimated_usd: float


class BudgetLedger:
    __slots__ = (
        "_global_budget_usd",
        "_hard_stop_usd",
        "_spent_usd",
        "_reservations",
        "_lock",
    )

    def __init__(
        self,
        global_budget_usd: float = 230.0,
        hard_stop_usd: float = 220.0,
        spent_usd: float = 0.0,
    ) -> None:
        global_budget = _finite_non_negative(global_budget_usd, "global_budget_usd")
        hard_stop = _finite_non_negative(hard_stop_usd, "hard_stop_usd")
        spent = _finite_non_negative(spent_usd, "spent_usd")
        if hard_stop > global_budget:
            raise ValueError("hard_stop_usd cannot exceed global_budget_usd")
        self._global_budget_usd = global_budget
        self._hard_stop_usd = hard_stop
        self._spent_usd = spent
        self._reservations: dict[str, float] = {}
        self._lock = Lock()

    @property
    def global_budget_usd(self) -> float:
        with self._lock:
            return self._global_budget_usd

    @property
    def hard_stop_usd(self) -> float:
        with self._lock:
            return self._hard_stop_usd

    @property
    def spent_usd(self) -> float:
        with self._lock:
            return self._spent_usd

    @property
    def reserved_usd(self) -> float:
        with self._lock:
            return sum(self._reservations.values())

    @property
    def remaining_usd(self) -> float:
        with self._lock:
            return self._remaining_usd()

    def estimate(self, seconds: float, profile: GPUProfile = L4) -> float:
        duration = _finite_non_negative(seconds, "seconds")
        rate = _finite_non_negative(profile.usd_per_hour, "usd_per_hour")
        estimated = duration * rate / 3600.0
        return _finite_non_negative(estimated, "estimated_usd")

    def authorize(
        self,
        job_id: str,
        estimated_seconds: float,
        job_cap_usd: float,
    ) -> BudgetReservation:
        cap = _finite_non_negative(job_cap_usd, "job_cap_usd")
        estimated = self.estimate(estimated_seconds)
        with self._lock:
            if job_id in self._reservations:
                return BudgetReservation(job_id, self._reservations[job_id])
            if estimated > cap:
                raise RuntimeError("estimated job cost exceeds job cap")
            if estimated > self._remaining_usd():
                raise RuntimeError("global GPU budget exhausted")
            self._reservations[job_id] = estimated
        return BudgetReservation(job_id, estimated)

    def record(self, job_id: str, actual_seconds: float) -> float:
        actual = self.estimate(actual_seconds)
        with self._lock:
            if job_id not in self._reservations:
                raise KeyError(f"unknown reservation: {job_id}")
            new_spent = _finite_non_negative(self._spent_usd + actual, "spent_usd")
            self._reservations.pop(job_id)
            self._spent_usd = new_spent
        return actual

    def release(self, job_id: str) -> None:
        with self._lock:
            self._reservations.pop(job_id, None)

    def _remaining_usd(self) -> float:
        available = min(self._global_budget_usd, self._hard_stop_usd)
        return max(0.0, available - self._spent_usd - sum(self._reservations.values()))
