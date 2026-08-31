"""The state machine is the cost control, so its shape is asserted directly."""

from __future__ import annotations

import pytest

from georeport3d.services.job_state import (
    ALL_STATES,
    INITIAL_STATE,
    TERMINAL_STATES,
    InvalidJobTransition,
    allowed_transitions,
    is_terminal,
    validate_transition,
)


def test_states_match_the_documented_machine() -> None:
    assert ALL_STATES == {
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
    }


def test_the_happy_path_runs_in_the_documented_order() -> None:
    path = [
        "QUEUED",
        "PRECHECKING",
        "CACHE_LOOKUP",
        "GPU_AUTHORIZED",
        "GPU_RUNNING",
        "VALIDATING",
        "PERSISTING",
        "COMPLETED",
    ]
    # Deliberately uneven: pairing each state with its successor drops the last.
    for current, target in zip(path, path[1:], strict=False):
        validate_transition(current, target)


def test_a_gpu_cannot_run_without_cache_lookup_and_authorization() -> None:
    # These are the transitions that would let a caller spend without checking the
    # cache or taking a reservation first.
    for current in ("QUEUED", "PRECHECKING"):
        with pytest.raises(InvalidJobTransition):
            validate_transition(current, "GPU_RUNNING")

    with pytest.raises(InvalidJobTransition):
        validate_transition("CACHE_LOOKUP", "GPU_RUNNING")


def test_a_cache_hit_completes_without_authorizing_a_gpu() -> None:
    validate_transition("CACHE_LOOKUP", "COMPLETED")


def test_validation_failure_cannot_reach_persistence() -> None:
    # docs/10: never return a successful extraction if validation fails.
    validate_transition("VALIDATING", "FAILED")
    assert "COMPLETED" not in allowed_transitions("VALIDATING")


def test_terminal_states_are_final() -> None:
    for state in TERMINAL_STATES:
        assert is_terminal(state)
        assert allowed_transitions(state) == frozenset()
        with pytest.raises(InvalidJobTransition, match="terminal"):
            validate_transition(state, "QUEUED")


def test_a_settled_job_cannot_be_revived() -> None:
    # Reviving a terminal job would let its reservation count against the budget
    # twice, because a terminal reservation has already stopped being outstanding.
    with pytest.raises(InvalidJobTransition):
        validate_transition("COMPLETED", "GPU_RUNNING")
    with pytest.raises(InvalidJobTransition):
        validate_transition("BUDGET_EXCEEDED", "PRECHECKING")


def test_a_running_job_can_be_cancelled_before_it_persists() -> None:
    for state in ("QUEUED", "PRECHECKING", "CACHE_LOOKUP", "GPU_AUTHORIZED", "GPU_RUNNING"):
        validate_transition(state, "CANCELLED")


def test_persisting_cannot_be_cancelled() -> None:
    # The result already exists at this point; it settles rather than vanishing.
    with pytest.raises(InvalidJobTransition):
        validate_transition("PERSISTING", "CANCELLED")


def test_unknown_states_are_rejected() -> None:
    with pytest.raises(InvalidJobTransition, match="unknown job state"):
        validate_transition("QUEUED", "NOT_A_STATE")
    with pytest.raises(InvalidJobTransition, match="unknown job state"):
        validate_transition("NOT_A_STATE", "QUEUED")
    with pytest.raises(InvalidJobTransition, match="unknown job state"):
        allowed_transitions("NOT_A_STATE")


def test_initial_state_is_queued() -> None:
    assert INITIAL_STATE == "QUEUED"
    assert not is_terminal(INITIAL_STATE)


def test_every_non_terminal_state_can_reach_a_terminal_state() -> None:
    # A job that could get stuck outside a terminal state would hold its budget
    # reservation forever.
    for state in ALL_STATES - TERMINAL_STATES:
        reachable = allowed_transitions(state)
        assert reachable, f"{state} has no outgoing transitions"
        assert reachable & TERMINAL_STATES, f"{state} cannot settle"
