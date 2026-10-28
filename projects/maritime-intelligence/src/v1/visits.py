"""Conservative geofence state machine. Silence never generates a departure."""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class VisitRules:
    arrival_observations: int
    arrival_seconds: int
    departure_observations: int
    departure_seconds: int
    gap_seconds: int


@dataclass(frozen=True)
class VisitState:
    phase: str = "unknown"
    since: datetime | None = None
    last_at: datetime | None = None
    count: int = 0
    arrival_at: datetime | None = None


def advance(state: VisitState, at: datetime, inside: bool, beyond_exit: bool, rules: VisitRules):
    """Return (state, transition). Caller processes only strictly increasing event time."""
    if state.last_at and at <= state.last_at:
        return state, None
    if state.last_at and at - state.last_at > timedelta(seconds=rules.gap_seconds):
        # Resume with new evidence; do not complete an earlier visit across a gap.
        state = VisitState()
    phase, since, count, arrival = state.phase, state.since, state.count, state.arrival_at
    transition = None
    if phase in {"unknown", "outside"}:
        arrival = None
        phase, since, count = ("candidate_arrival", at, 1) if inside else ("outside", at, 0)
    elif phase == "candidate_arrival":
        if not inside:
            phase, since, count = "outside", at, 0
        else:
            count += 1
            if count >= rules.arrival_observations and at - since >= timedelta(
                seconds=rules.arrival_seconds
            ):
                phase, arrival, transition = "inside", since, "arrival"
    elif phase == "inside" and beyond_exit:
        phase, since, count = "candidate_departure", at, 1
    elif phase == "candidate_departure":
        if inside:
            phase, count = "inside", 0
        elif beyond_exit:
            count += 1
            if count >= rules.departure_observations and at - since >= timedelta(
                seconds=rules.departure_seconds
            ):
                phase, transition = "outside", "departure"
    return VisitState(phase, since, at, count, arrival), transition
