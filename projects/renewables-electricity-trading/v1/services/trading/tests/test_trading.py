import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier
from unittest.mock import patch
import pytest
from django.db import close_old_connections
from django.utils import timezone
from django.contrib.auth.models import User
from app.calendar import periods
from app.models import (
    Portfolio,
    Membership,
    Counterparty,
    Position,
    Trade,
    TradeRevision,
    Outbox,
    Decision,
)
from app.serializers import TradeSerializer
from app.domain import book, reconcile
from app.events import apply_event

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(user):
    start = (timezone.now() + timedelta(days=1)).replace(hour=13, minute=0, second=0, microsecond=0)
    p = Portfolio.objects.create(id="desk", name="desk", lower_limit=0, upper_limit=200)
    Membership.objects.create(user=user, portfolio=p, role="trader")
    Counterparty.objects.create(id="buyer", name="Buyer")
    Position.objects.create(
        portfolio=p,
        start=start,
        forecast=100,
        forecast_revision=1,
        forecast_valid_until=timezone.now() + timedelta(days=2),
    )
    return p, start


def payload(start, quantity="80.000"):
    return {
        "portfolio": "desk",
        "counterparty": "buyer",
        "direction": "SELL",
        "reason": "test trade",
        "legs": [{"start": start.isoformat(), "quantity": quantity, "price": "70.0000"}],
    }


def submit(user, start, key="request", quantity="80.000"):
    data = payload(start, quantity)
    s = TradeSerializer(data=data)
    s.is_valid(raise_exception=True)
    return book(user, key, data, s.validated_data)


def test_calendar():
    assert len(periods(date(2026, 3, 29))) == 46
    assert len(periods(date(2026, 10, 25))) == 50
    assert len(periods(date(2026, 10, 26))) == 48
    assert len(set(periods(date(2026, 10, 25)))) == 50


def test_accept_retry_and_reject(setup, user):
    p, start = setup
    first, status, _ = submit(user, start)
    assert status == 201
    again, _, replay = submit(user, start)
    assert replay and again == first
    assert Trade.objects.count() == 1
    assert Position.objects.get(portfolio=p, start=start).sales == 80
    assert submit(user, start, "second", "21.000")[1] == 422
    assert Trade.objects.count() == 1
    assert Decision.objects.count() == 2


def test_key_conflict(setup, user):
    from app.common import Conflict

    _, start = setup
    submit(user, start)
    with pytest.raises(Conflict):
        submit(user, start, quantity="79.000")


def test_expired_forecast(setup, user):
    _, start = setup
    Position.objects.update(forecast_valid_until=timezone.now() - timedelta(seconds=1))
    assert submit(user, start)[0]["code"] == "forecast_missing_or_expired"


def test_permissions(setup, client, user):
    _, start = setup
    assert (
        client.post(
            "/v1/trades", payload(start), format="json", HTTP_IDEMPOTENCY_KEY="api"
        ).status_code
        == 201
    )
    Membership.objects.update(role="viewer")
    assert (
        client.post(
            "/v1/trades", payload(start), format="json", HTTP_IDEMPOTENCY_KEY="next"
        ).status_code
        == 403
    )
    assert client.get("/v1/portfolios/other/positions").status_code == 403


def test_amend_cancel_and_audit(setup, client):
    p, start = setup
    accepted = client.post(
        "/v1/trades", payload(start), format="json", HTTP_IDEMPOTENCY_KEY="a"
    ).json()
    trade_id = accepted["trade"]["id"]
    amended = {**payload(start, "60.000"), "expected_revision": 1}
    response = client.post(
        f"/v1/trades/{trade_id}/amendments", amended, format="json", HTTP_IDEMPOTENCY_KEY="b"
    )
    assert response.status_code == 200
    assert Position.objects.get(portfolio=p).sales == 60
    assert (
        client.post(
            f"/v1/trades/{trade_id}/amendments", amended, format="json", HTTP_IDEMPOTENCY_KEY="c"
        ).status_code
        == 409
    )
    response = client.post(
        f"/v1/trades/{trade_id}/cancellations",
        {"expected_revision": 2, "reason": "Agreed cancellation"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="d",
    )
    assert response.status_code == 200
    assert Position.objects.get(portfolio=p).sales == 0
    assert TradeRevision.objects.count() == 3


def test_rollback_including_position_and_outbox(setup, user):
    p, start = setup
    with patch("app.domain.emit", side_effect=RuntimeError("simulated failure")):
        with pytest.raises(RuntimeError):
            submit(user, start)
    assert (
        Trade.objects.count() == 0 and Outbox.objects.count() == 0 and Decision.objects.count() == 0
    )
    assert Position.objects.get(portfolio=p).sales == 0


def test_multi_interval_reject_is_atomic(setup, user):
    p, start = setup
    other = start + timedelta(minutes=30)
    Position.objects.create(
        portfolio=p,
        start=other,
        forecast=1,
        forecast_revision=1,
        forecast_valid_until=timezone.now() + timedelta(days=2),
    )
    raw = payload(start)
    raw["legs"].append({"start": other.isoformat(), "quantity": "2.000", "price": "70.0000"})
    s = TradeSerializer(data=raw)
    s.is_valid(raise_exception=True)
    assert book(user, "multi", raw, s.validated_data)[1] == 422
    assert not Trade.objects.exists()
    assert all(x.sales == 0 for x in Position.objects.all())


def test_reconciliation_blocks_then_repairs(setup, user):
    p, start = setup
    submit(user, start)
    Position.objects.update(sales=0)
    assert reconcile(p.pk).mismatches
    p.refresh_from_db()
    assert p.writes_blocked
    assert reconcile(p.pk, repair=True).mismatches
    assert not reconcile(p.pk).mismatches
    p.refresh_from_db()
    assert not p.writes_blocked


def forecast_event(start, revision, quantity):
    return {
        "event_id": str(uuid.uuid4()),
        "schema_version": 1,
        "type": "forecast.updated",
        "entity_id": "forecast:desk",
        "revision": revision,
        "occurred_at": timezone.now().isoformat(),
        "data": {
            "portfolio": "desk",
            "start": start.isoformat(),
            "quantity": str(quantity),
            "published_at": timezone.now().isoformat(),
            "valid_until": (timezone.now() + timedelta(days=2)).isoformat(),
        },
    }


def test_forecast_revision_dedup_and_risk_reduction(setup, user, event_guard):
    p, start = setup
    submit(user, start)
    event = forecast_event(start, 3, 60)
    assert apply_event(event)
    assert not apply_event(event)
    apply_event(forecast_event(start, 2, 90))
    pos = Position.objects.get(portfolio=p)
    assert pos.forecast == 60
    raw = payload(start, "10.000")
    raw["direction"] = "BUY"
    s = TradeSerializer(data=raw)
    s.is_valid(raise_exception=True)
    assert book(user, "cover", raw, s.validated_data)[1] == 201
    assert submit(user, start, "worsen", "1.000")[1] == 422


@pytest.mark.django_db(transaction=True)
def test_competing_bookings_serialize():
    user = User.objects.create_user(username="racer")
    p = Portfolio.objects.create(id="desk", name="desk", lower_limit=0, upper_limit=200)
    Membership.objects.create(user=user, portfolio=p, role="trader")
    Counterparty.objects.create(id="buyer", name="Buyer")
    start = (timezone.now() + timedelta(days=1)).replace(hour=13, minute=0, second=0, microsecond=0)
    Position.objects.create(
        portfolio=p,
        start=start,
        forecast=10,
        forecast_revision=1,
        forecast_valid_until=timezone.now() + timedelta(days=2),
    )
    barrier = Barrier(2)

    def race(index):
        close_old_connections()
        try:
            actor = User.objects.get(pk=user.pk)
            barrier.wait(timeout=5)
            return submit(actor, start, f"race-{index}", "8.000")[1]
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(race, [1, 2]))
    assert sorted(results) == [201, 422]
    assert Trade.objects.count() == 1
    assert Position.objects.get(portfolio=p).sales == 8


@pytest.mark.django_db(transaction=True)
def test_duplicate_requests_serialize():
    user = User.objects.create_user(username="duplicate")
    p = Portfolio.objects.create(id="desk", name="desk", lower_limit=0, upper_limit=200)
    Membership.objects.create(user=user, portfolio=p, role="trader")
    Counterparty.objects.create(id="buyer", name="Buyer")
    start = (timezone.now() + timedelta(days=1)).replace(hour=13, minute=0, second=0, microsecond=0)
    Position.objects.create(
        portfolio=p,
        start=start,
        forecast=100,
        forecast_revision=1,
        forecast_valid_until=timezone.now() + timedelta(days=2),
    )
    barrier = Barrier(2)

    def race(_):
        close_old_connections()
        try:
            actor = User.objects.get(pk=user.pk)
            barrier.wait(timeout=5)
            return submit(actor, start, "same")[2]
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(race, [1, 2]))
    assert sorted(results) == [False, True] and Trade.objects.count() == 1


def test_cannot_cross_into_opposite_breach(setup, user, event_guard):
    p, start = setup
    submit(user, start)
    apply_event(forecast_event(start, 2, 60))
    raw = payload(start, "230.000")
    raw["direction"] = "BUY"
    serializer = TradeSerializer(data=raw)
    serializer.is_valid(raise_exception=True)
    assert book(user, "over-cover", raw, serializer.validated_data)[1] == 422
    assert Position.objects.get(portfolio=p).purchases == 0


def test_api_replays_after_delivery_passes(setup, client):
    _, start = setup
    body = payload(start)
    first = client.post("/v1/trades", body, format="json", HTTP_IDEMPOTENCY_KEY="historical")
    assert first.status_code == 201
    with patch("app.serializers.timezone.now", return_value=start + timedelta(days=1)):
        replay = client.post("/v1/trades", body, format="json", HTTP_IDEMPOTENCY_KEY="historical")
    assert replay.status_code == 201 and replay["Idempotent-Replay"] == "true"


def test_risk_only_limits_and_revision(setup, client, user):
    p, _ = setup
    data = {"lower": "0.000", "upper": "100.000", "expected_revision": 1, "reason": "Risk review"}
    assert client.put("/v1/portfolios/desk/limits", data, format="json").status_code == 403
    Membership.objects.filter(user=user).update(role="risk")
    assert client.put("/v1/portfolios/desk/limits", data, format="json").status_code == 200
    assert client.put("/v1/portfolios/desk/limits", data, format="json").status_code == 409


@pytest.mark.django_db(transaction=True)
def test_competing_amendments():
    from app.serializers import AmendmentSerializer
    from app.common import Conflict

    user = User.objects.create_user(username="amender")
    p = Portfolio.objects.create(id="desk", name="desk", lower_limit=0, upper_limit=200)
    Membership.objects.create(user=user, portfolio=p, role="trader")
    Counterparty.objects.create(id="buyer", name="Buyer")
    start = (timezone.now() + timedelta(days=1)).replace(hour=13, minute=0, second=0, microsecond=0)
    Position.objects.create(
        portfolio=p,
        start=start,
        forecast=100,
        forecast_revision=1,
        forecast_valid_until=timezone.now() + timedelta(days=2),
    )
    result, _, _ = submit(user, start)
    trade_id = result["trade"]["id"]
    barrier = Barrier(2)

    def amend(index):
        close_old_connections()
        try:
            actor = User.objects.get(pk=user.pk)
            raw = {**payload(start, str(60 + index)), "expected_revision": 1}
            serializer = AmendmentSerializer(data=raw)
            serializer.is_valid(raise_exception=True)
            barrier.wait(timeout=5)
            try:
                return book(actor, f"amend-{index}", raw, serializer.validated_data, trade_id)[1]
            except Conflict:
                return 409
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(amend, [1, 2]))
    assert sorted(results) == [200, 409]
    assert Trade.objects.get().revision == 2
    assert not reconcile(p.pk).mismatches


@pytest.mark.django_db(transaction=True)
def test_commit_before_ack_is_safe(setup, user, event_guard):
    import json
    from unittest.mock import Mock
    from app.events import process_message

    p, start = setup
    event = forecast_event(start, 3, 60)
    client = Mock()
    client.delete_message.side_effect = RuntimeError("lost acknowledgement")
    message = {"Body": json.dumps(event), "ReceiptHandle": "receipt"}
    process_message(message, "local", client)
    assert Position.objects.get(portfolio=p).forecast_revision == 3
    client.delete_message.side_effect = None
    process_message(message, "local", client)
    assert Position.objects.get(portfolio=p).forecast_revision == 3


def test_decision_retains_economic_inputs(setup, user):
    _, start = setup
    result, _, _ = submit(user, start)
    original = result["decision"]
    assert original["limits"] == {"lower": "0.000", "upper": "200.000"}
    assert original["forecasts"][0]["quantity"] == "100.000"
    assert original["forecasts"][0]["exposure_after"] == "20.000"
    Position.objects.update(forecast=60, forecast_revision=2)
    replay, _, _ = submit(user, start)
    assert replay["decision"] == original
