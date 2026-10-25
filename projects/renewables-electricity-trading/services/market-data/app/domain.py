from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.db import transaction
from django.utils import timezone
from .models import MarketValue, MarketRevision, ConsumerGuard
from .events import emit


def seed_domain():
    pass


def handle_event(event):
    raise ValueError("Market Data does not consume business events")


def scenario_start():
    tomorrow = timezone.now().astimezone(ZoneInfo("Europe/London")).date() + timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, 13, tzinfo=dt_timezone.utc)


def write_value(
    kind, portfolio, start, quantity, published_at, valid_until, provenance="synthetic"
):
    if kind not in ["forecast", "meter", "price"]:
        raise ValueError("Unknown data kind")
    quantity = Decimal(str(quantity))
    if not quantity.is_finite() or abs(quantity) > 100000 or (kind != "price" and quantity < 0):
        raise ValueError("Invalid quantity")
    if start.tzinfo is None or start.minute not in (0, 30) or start.second or start.microsecond:
        raise ValueError("Invalid interval")
    if published_at.tzinfo is None or valid_until <= published_at:
        raise ValueError("Invalid publication/validity")
    if provenance != "synthetic":
        raise ValueError("Portfolio values must explicitly be synthetic in V1")
    with transaction.atomic():
        ConsumerGuard.objects.select_for_update().get(name="events")
        value = MarketValue.objects.filter(kind=kind, portfolio=portfolio, start=start).first()
        if value:
            if published_at < value.published_at:
                return value
            if value.quantity == quantity and value.published_at == published_at:
                return value
            value.revision += 1
            value.quantity = quantity
            value.published_at = published_at
            value.valid_until = valid_until
            value.save()
        else:
            value = MarketValue.objects.create(
                kind=kind,
                portfolio=portfolio,
                start=start,
                quantity=quantity,
                published_at=published_at,
                valid_until=valid_until,
                provenance=provenance,
            )
        data = {
            "portfolio": portfolio,
            "start": start.isoformat(),
            "quantity": str(quantity),
            "published_at": published_at.isoformat(),
            "valid_until": valid_until.isoformat(),
            "provenance": provenance,
        }
        MarketRevision.objects.create(value=value, revision=value.revision, payload=data)
        emit(
            f"{kind}.updated",
            f"{kind}:{portfolio}:{start.isoformat()}",
            value.revision,
            data,
            ["valuation-input"] if kind == "price" else ["trading-input"],
        )
        return value
