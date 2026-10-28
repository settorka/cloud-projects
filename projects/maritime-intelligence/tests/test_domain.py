import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from v1.adapters.digitraffic import normalize
from v1.models import Observation, freshness
from v1.visits import VisitRules, VisitState, advance

RULES = VisitRules(3, 300, 2, 120, 600)
AT = datetime(2026, 10, 28, 10, tzinfo=UTC)


def observation(**kwargs):
    return Observation(
        **{
            "source": "test",
            "mmsi": "230123456",
            "event_time": AT,
            "received_at": AT,
            "lon": 24.9,
            "lat": 60.1,
            **kwargs,
        }
    )


def test_receipt_changes_do_not_change_identity():
    first = observation()
    assert first.event_id == replace(first, received_at=AT + timedelta(minutes=2)).event_id
    assert first.event_id != replace(first, lon=25).event_id


@pytest.mark.parametrize(
    "changes",
    [
        {"lat": 91},
        {"lon": float("nan")},
        {"mmsi": "２３０１２３４５６"},
        {"cog": 360},
        {"event_time": AT + timedelta(minutes=6)},
        {"event_time": AT.replace(tzinfo=None)},
    ],
)
def test_invalid_values_rejected(changes):
    with pytest.raises(ValueError):
        observation(**changes)


def test_digitraffic_seconds_and_missing_sentinels():
    raw = {"time": AT.timestamp(), "lon": 24.9, "lat": 60.1, "sog": 102.3, "cog": 360}
    o, _ = normalize("vessels-v2/230123456/location", json.dumps(raw).encode(), AT)
    assert o.event_time == AT
    assert o.sog is None and o.cog is None
    raw["time"] *= 1000
    with pytest.raises((ValueError, OverflowError)):
        normalize("vessels-v2/230123456/location", json.dumps(raw).encode(), AT)


def test_confirmed_visit_requires_dwell_and_departure_evidence():
    state = VisitState()
    for minutes in [0, 2, 5]:
        state, transition = advance(state, AT + timedelta(minutes=minutes), True, False, RULES)
    assert state.phase == "inside" and transition == "arrival"
    assert state.arrival_at == AT
    state, transition = advance(state, AT + timedelta(minutes=6), False, True, RULES)
    assert transition is None
    state, transition = advance(state, AT + timedelta(minutes=8), False, True, RULES)
    assert state.phase == "outside" and transition == "departure"


def test_silence_and_delayed_data_cannot_confirm_departure():
    state = VisitState("inside", AT, AT, 3, AT)
    assert advance(state, AT - timedelta(minutes=1), False, True, RULES) == (state, None)
    after, transition = advance(state, AT + timedelta(minutes=11), False, True, RULES)
    assert transition is None and after.arrival_at is None


def test_boundary_jitter_does_not_confirm_exit():
    state = VisitState("inside", AT, AT, 3, AT)
    after, transition = advance(state, AT + timedelta(minutes=1), False, False, RULES)
    assert after.phase == "inside" and transition is None


def test_freshness_includes_unknown_and_expired():
    assert freshness(AT, AT, 300, 1800) == "fresh"
    assert freshness(AT, AT + timedelta(minutes=6), 300, 1800) == "stale"
    assert freshness(AT, AT + timedelta(minutes=31), 300, 1800) == "expired"
    assert freshness(AT + timedelta(minutes=6), AT, 300, 1800) == "unknown"
