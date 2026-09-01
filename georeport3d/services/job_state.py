"""The inference job state machine from `docs/10_API_AND_JOB_STATE.md`.

The order encoded here is the cost control. A job cannot reach `GPU_RUNNING`
without passing through `CACHE_LOOKUP` and `GPU_AUTHORIZED` first, so no code path
can spend on a GPU without having checked the cache and taken a budget
reservation. Expressing that as data rather than as branches means a new caller
cannot invent a shortcut around it.

Terminal states are final. A job that has settled must not be revived, because its
reservation has already stopped counting against the budget and reopening it would
let the same work reserve twice.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

JobState = Literal[
    "QUEUED",
    "PRECHECKING",
    "CACHE_LOOKUP",
    "GPU_AUTHORIZED",
    "GPU_RUNNING",
    "VALIDATING",
    "PERSISTING",
    "COMPLETED",
    "REJECTED",
    "CANCELLED",
    "FAILED",
    "BUDGET_EXCEEDED",
    "TIMEOUT",
]

ALL_STATES: Final[frozenset[str]] = frozenset(get_args(JobState))

TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {"COMPLETED", "REJECTED", "CANCELLED", "FAILED", "BUDGET_EXCEEDED", "TIMEOUT"}
)

INITIAL_STATE: Final[JobState] = "QUEUED"

# States in which a job holds a GPU slot. A job is counted from the moment it is
# authorized rather than when it starts running, because the slot is spoken for as
# soon as the reservation exists.
GPU_SLOT_STATES: Final[frozenset[str]] = frozenset({"GPU_AUTHORIZED", "GPU_RUNNING"})


class StaleJobState(RuntimeError):
    """A transition was attempted from a state the job is no longer in."""

# States from which a running job may still be abandoned by the operator or by a
# failure. A job already past PERSISTING has written its result, so it settles as
# COMPLETED or FAILED rather than being cancelled.
_ABANDONABLE: Final[tuple[str, ...]] = ("CANCELLED", "FAILED", "TIMEOUT")

_TRANSITIONS: Final[dict[str, tuple[str, ...]]] = {
    "QUEUED": ("PRECHECKING", "REJECTED", *_ABANDONABLE),
    # Precheck decides admissibility before any lookup or spend.
    "PRECHECKING": ("CACHE_LOOKUP", "REJECTED", "BUDGET_EXCEEDED", *_ABANDONABLE),
    # A cache hit settles the job without ever authorising a GPU. REJECTED is
    # reachable because admission now happens after the lookup: a miss that policy
    # refuses - unconfirmed spend, no free GPU slot - is refused from here, having
    # already established that the answer was not already known.
    "CACHE_LOOKUP": (
        "GPU_AUTHORIZED",
        "COMPLETED",
        "REJECTED",
        "BUDGET_EXCEEDED",
        *_ABANDONABLE,
    ),
    "GPU_AUTHORIZED": ("GPU_RUNNING", *_ABANDONABLE),
    "GPU_RUNNING": ("VALIDATING", *_ABANDONABLE),
    # Validation failure is terminal: a result that fails schema or provenance
    # validation must never be persisted as an extraction.
    "VALIDATING": ("PERSISTING", "FAILED", "TIMEOUT"),
    "PERSISTING": ("COMPLETED", "FAILED"),
}


class InvalidJobTransition(ValueError):
    """A transition that the job state machine does not allow."""


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def allowed_transitions(state: str) -> frozenset[str]:
    """Return the states reachable in one step from `state`."""
    if state not in ALL_STATES:
        raise InvalidJobTransition(f"unknown job state: {state}")
    return frozenset(_TRANSITIONS.get(state, ()))


def validate_transition(current: str, target: str) -> None:
    """Raise unless moving from `current` to `target` is permitted."""
    if current not in ALL_STATES:
        raise InvalidJobTransition(f"unknown job state: {current}")
    if target not in ALL_STATES:
        raise InvalidJobTransition(f"unknown job state: {target}")
    if is_terminal(current):
        raise InvalidJobTransition(f"{current} is terminal and cannot transition")
    if target not in _TRANSITIONS.get(current, ()):
        raise InvalidJobTransition(f"{current} cannot transition to {target}")
