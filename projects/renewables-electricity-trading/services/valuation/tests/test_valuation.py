import uuid
from datetime import timedelta
from decimal import Decimal
import pytest
from django.utils import timezone
from app.models import Price, TradeCopy, PortfolioAccess
from app.domain import calculate
from app.events import apply_event

pytestmark = pytest.mark.django_db


def trade(start, direction="BUY", price="70", revision=1):
    id = str(uuid.uuid4())
    data = {
        "id": id,
        "portfolio": "demo",
        "counterparty": "buyer",
        "direction": direction,
        "revision": revision,
        "state": "ACTIVE",
        "legs": [{"start": start.isoformat(), "quantity": "10", "price": price}],
    }
    return data


def event(data, revision=None):
    return {
        "event_id": str(uuid.uuid4()),
        "schema_version": 1,
        "type": "trade.changed",
        "entity_id": data["id"],
        "revision": revision or data["revision"],
        "occurred_at": timezone.now().isoformat(),
        "data": data,
    }


@pytest.mark.parametrize("direction,expected", [("BUY", Decimal("100")), ("SELL", Decimal("-100"))])
def test_value_and_reproduce(event_guard, direction, expected):
    now = timezone.now()
    start = now.replace(minute=0, second=0, microsecond=0)
    Price.objects.create(
        start=start, revision=1, value=80, published_at=now, valid_until=now + timedelta(days=1)
    )
    data = trade(start, direction)
    apply_event(event(data))
    run = calculate("demo")
    again = calculate("demo")
    assert (
        run.total == expected
        and run.results == again.results
        and run.input_versions == again.input_versions
    )
    assert run.state == "CURRENT"


def test_missing_price_and_cancel(event_guard):
    now = timezone.now().replace(minute=0, second=0, microsecond=0)
    data = trade(now)
    original = event(data)
    assert apply_event(original)
    assert not apply_event(original)
    assert calculate("demo").total is None
    cancelled = {**data, "revision": 2, "state": "CANCELLED", "legs": []}
    apply_event(event(cancelled))
    apply_event(event(data))
    assert TradeCopy.objects.get().revision == 2
    assert calculate("demo").total == 0


def test_stale_and_negative_prices(event_guard):
    now = timezone.now()
    start = now.replace(minute=0, second=0, microsecond=0)
    Price.objects.create(
        start=start,
        revision=1,
        value=-20,
        published_at=now - timedelta(days=1),
        valid_until=now - timedelta(seconds=1),
    )
    apply_event(event(trade(start, price="-30")))
    run = calculate("demo")
    assert run.total == 100 and run.state == "STALE"


def test_portfolio_access(client, user, event_guard):
    assert (
        client.post("/v1/valuation-runs", {"portfolio": "private"}, format="json").status_code
        == 403
    )
    PortfolioAccess.objects.create(user=user, portfolio="demo")
    assert (
        client.post("/v1/valuation-runs", {"portfolio": "demo"}, format="json").status_code == 201
    )
