import hashlib
import json
import time
from decimal import Decimal
from django.db import connection, transaction
from django.http import Http404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError
from .models import (
    Portfolio,
    Membership,
    Counterparty,
    Asset,
    Position,
    Trade,
    TradeRevision,
    TradeLeg,
    Decision,
    Audit,
    Reconciliation,
    JobStatus,
)
from .common import Conflict, Forbidden
from .events import emit
from .observability import LOCK_TIME

ZERO = Decimal("0")


def seed_domain():
    from django.contrib.auth.models import User

    for slug in ["demo", "restricted"]:
        Portfolio.objects.get_or_create(id=slug, defaults={"name": slug})
    for role in ["trader", "risk", "viewer"]:
        Membership.objects.update_or_create(
            user=User.objects.get(username=role), portfolio_id="demo", defaults={"role": role}
        )
    Counterparty.objects.get_or_create(id="grid-buyer", defaults={"name": "Synthetic counterparty"})
    Asset.objects.get_or_create(
        id="demo-wind", defaults={"portfolio_id": "demo", "technology": "wind", "capacity_mw": 200}
    )


def membership(user, portfolio, write=False, risk=False):
    item = Membership.objects.filter(user=user, portfolio_id=portfolio).first()
    if (
        not item
        or (write and item.role not in ["trader", "risk"])
        or (risk and item.role != "risk")
    ):
        raise Forbidden()
    return item


def locked_portfolio(pk):
    start = time.monotonic()
    try:
        result = Portfolio.objects.select_for_update().get(pk=pk)
    except Portfolio.DoesNotExist:
        raise Http404()
    LOCK_TIME.observe(time.monotonic() - start)
    return result


def snapshot(trade, legs):
    return {
        "id": str(trade.pk),
        "portfolio": trade.portfolio_id,
        "counterparty": trade.counterparty_id,
        "direction": trade.direction,
        "revision": trade.revision,
        "state": trade.state,
        "legs": [
            {
                "start": x["start"].isoformat(),
                "quantity": str(x["quantity"]),
                "price": str(x["price"]),
            }
            for x in legs
        ],
    }


def distance(value, portfolio):
    return max(ZERO, portfolio.lower_limit - value, value - portfolio.upper_limit)


def request_fingerprint(raw, trade_id=None, cancel=False):
    scope = {
        "operation": "cancel" if cancel else "amend" if trade_id else "book",
        "trade": str(trade_id) if trade_id else None,
        "body": raw,
    }
    return hashlib.sha256(
        json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def replay_decision(user, key, raw, trade_id=None, cancel=False):
    if not key or len(key) > 100:
        raise ValidationError({"Idempotency-Key": "Required; maximum 100 characters"})
    old = Decision.objects.filter(user=user, key=key).first()
    if old:
        if old.fingerprint != request_fingerprint(raw, trade_id, cancel):
            raise Conflict("Idempotency key reused with different input")
        membership(user, old.response["portfolio"], write=True)
    return old


def book(user, key, raw, validated, trade_id=None, cancel=False):
    if not key or len(key) > 100:
        raise ValidationError({"Idempotency-Key": "Required; maximum 100 characters"})
    fingerprint = request_fingerprint(raw, trade_id, cancel)
    # The key is scoped to actor, independent of portfolio and route.
    advisory = int.from_bytes(
        hashlib.sha256(f"{user.pk}:{key}".encode()).digest()[:8], "big", signed=True
    )
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [advisory])
        old = Decision.objects.filter(user=user, key=key).first()
        if old:
            if old.fingerprint != fingerprint:
                raise Conflict("Idempotency key reused with different input")
            membership(user, old.response["portfolio"], write=True)
            return old.response, old.http_status, True
        trade = Trade.objects.filter(pk=trade_id).first() if trade_id else None
        if trade_id and not trade:
            raise Http404()
        portfolio_id = trade.portfolio_id if trade else validated["portfolio"]
        membership(user, portfolio_id, write=True)
        portfolio = locked_portfolio(portfolio_id)
        if portfolio.writes_blocked:
            raise Conflict("Portfolio blocked pending reconciliation")
        previous = []
        if trade:
            trade.refresh_from_db()
            if trade.state != "ACTIVE":
                raise Conflict("Trade is already cancelled")
            if trade.revision != validated["expected_revision"]:
                raise Conflict("Stale trade revision")
            previous = TradeRevision.objects.get(trade=trade, number=trade.revision).snapshot[
                "legs"
            ]
            previous = [
                {
                    "start": parse_datetime(x["start"]),
                    "quantity": Decimal(x["quantity"]),
                    "price": Decimal(x["price"]),
                }
                for x in previous
            ]
            if not cancel and validated["portfolio"] != portfolio_id:
                raise ValidationError("Cannot move trades between portfolios")
        if any(leg["start"] <= timezone.now() for leg in previous):
            raise ValidationError("Cannot amend or cancel delivered intervals")
        if not cancel and not Counterparty.objects.filter(pk=validated["counterparty"]).exists():
            raise ValidationError("Unknown counterparty")
        new = [] if cancel else validated["legs"]
        starts = sorted({x["start"] for x in previous + new})
        changes = {s: {"purchases": ZERO, "sales": ZERO} for s in starts}
        if trade:
            for leg in previous:
                changes[leg["start"]]["purchases" if trade.direction == "BUY" else "sales"] -= leg[
                    "quantity"
                ]
        if not cancel:
            for leg in new:
                changes[leg["start"]][
                    "purchases" if validated["direction"] == "BUY" else "sales"
                ] += leg["quantity"]
        positions = []
        inputs = {
            "limit_revision": portfolio.limit_revision,
            "limits": {"lower": str(portfolio.lower_limit), "upper": str(portfolio.upper_limit)},
            "policy": "interval-exposure-v1",
            "forecasts": [],
        }
        rejection = None
        for start in starts:
            pos, _ = Position.objects.get_or_create(portfolio=portfolio, start=start)
            inputs["forecasts"].append(
                {
                    "start": start.isoformat(),
                    "revision": pos.forecast_revision,
                    "quantity": str(pos.forecast) if pos.forecast is not None else None,
                    "published_at": pos.forecast_published_at.isoformat()
                    if pos.forecast_published_at
                    else None,
                    "valid_until": pos.forecast_valid_until.isoformat()
                    if pos.forecast_valid_until
                    else None,
                    "purchases_before": str(pos.purchases),
                    "sales_before": str(pos.sales),
                }
            )
            if (
                pos.forecast is None
                or not pos.forecast_valid_until
                or pos.forecast_valid_until <= timezone.now()
            ):
                rejection = "forecast_missing_or_expired"
                continue
            before = pos.forecast + pos.purchases - pos.sales
            after = before + changes[start]["purchases"] - changes[start]["sales"]
            inputs["forecasts"][-1].update(
                {"exposure_before": str(before), "exposure_after": str(after)}
            )
            old_distance = distance(before, portfolio)
            new_distance = distance(after, portfolio)
            crosses_breach = (before < portfolio.lower_limit and after > portfolio.upper_limit) or (
                before > portfolio.upper_limit and after < portfolio.lower_limit
            )
            if (
                crosses_breach
                or (old_distance == 0 and new_distance > 0)
                or (old_distance > 0 and new_distance >= old_distance)
            ):
                rejection = "position_limit"
            positions.append(pos)
        if rejection:
            response = {
                "outcome": "REJECTED",
                "code": rejection,
                "portfolio": portfolio_id,
                "decision": inputs,
            }
            Decision.objects.create(
                user=user,
                key=key,
                fingerprint=fingerprint,
                http_status=422,
                response=response,
                inputs=inputs,
            )
            return response, 422, False
        if trade:
            trade.revision += 1
            if cancel:
                trade.state = "CANCELLED"
            else:
                trade.direction = validated["direction"]
                trade.counterparty_id = validated["counterparty"]
            trade.save()
        else:
            trade = Trade.objects.create(
                portfolio=portfolio,
                counterparty_id=validated["counterparty"],
                direction=validated["direction"],
            )
        for pos in positions:
            pos.purchases += changes[pos.start]["purchases"]
            pos.sales += changes[pos.start]["sales"]
            pos.save(update_fields=["purchases", "sales"])
        data = snapshot(trade, new)
        revision = TradeRevision.objects.create(
            trade=trade,
            number=trade.revision,
            snapshot=data,
            actor=user,
            reason=validated["reason"],
        )
        TradeLeg.objects.bulk_create([TradeLeg(revision=revision, **leg) for leg in new])
        Audit.objects.create(
            actor=user.username,
            action="trade.cancelled" if cancel else "trade.amended" if trade_id else "trade.booked",
            portfolio=portfolio,
            details={
                "trade_id": str(trade.pk),
                "revision": trade.revision,
                "reason": validated["reason"],
                "inputs": inputs,
            },
        )
        emit("trade.changed", trade.pk, trade.revision, data, ["valuation-input"])
        response = {
            "outcome": "ACCEPTED",
            "portfolio": portfolio_id,
            "trade": data,
            "decision": inputs,
        }
        Decision.objects.create(
            user=user,
            key=key,
            fingerprint=fingerprint,
            http_status=200 if trade_id else 201,
            response=response,
            inputs=inputs,
        )
        return response, 200 if trade_id else 201, False


def handle_event(event):
    if event["type"] not in ["forecast.updated", "meter.updated"]:
        raise ValueError("Unsupported Trading event")
    data = event["data"]
    portfolio = locked_portfolio(data["portfolio"])
    start = parse_datetime(data["start"])
    if (
        start is None
        or start.tzinfo is None
        or start.minute not in (0, 30)
        or start.second
        or start.microsecond
    ):
        raise ValueError("Invalid interval")
    quantity = Decimal(data["quantity"])
    if not quantity.is_finite() or quantity < 0 or quantity > Decimal("100000"):
        raise ValueError("Invalid generation quantity")
    pos, _ = Position.objects.get_or_create(portfolio=portfolio, start=start)
    if event["type"] == "forecast.updated":
        if event["revision"] <= pos.forecast_revision:
            return
        published = parse_datetime(data["published_at"])
        valid = parse_datetime(data["valid_until"])
        if (
            not published
            or not valid
            or not published.tzinfo
            or not valid.tzinfo
            or valid <= published
        ):
            raise ValueError("Invalid forecast validity")
        pos.forecast = quantity
        pos.forecast_revision = event["revision"]
        pos.forecast_published_at = published
        pos.forecast_valid_until = valid
    else:
        if event["revision"] <= pos.meter_revision:
            return
        pos.meter = quantity
        pos.meter_revision = event["revision"]
    pos.save()
    Audit.objects.create(
        actor="market-data",
        action=event["type"],
        portfolio=portfolio,
        details={
            "event_id": event["event_id"],
            "start": start.isoformat(),
            "revision": event["revision"],
        },
    )


def reconcile(portfolio_id, repair=False):
    with transaction.atomic():
        portfolio = locked_portfolio(portfolio_id)
        expected = {}
        for trade in Trade.objects.filter(portfolio=portfolio, state="ACTIVE"):
            revision = TradeRevision.objects.get(trade=trade, number=trade.revision)
            for leg in revision.legs.all():
                item = expected.setdefault(leg.start, {"purchases": ZERO, "sales": ZERO})
                item["purchases" if trade.direction == "BUY" else "sales"] += leg.quantity
        actual = {p.start: p for p in Position.objects.filter(portfolio=portfolio)}
        mismatches = []
        for start in sorted(set(expected) | set(actual)):
            values = expected.get(start, {"purchases": ZERO, "sales": ZERO})
            pos = actual.get(start)
            if pos is None or pos.purchases != values["purchases"] or pos.sales != values["sales"]:
                mismatches.append(
                    {"start": start.isoformat(), "expected": {k: str(v) for k, v in values.items()}}
                )
                if repair:
                    Position.objects.update_or_create(
                        portfolio=portfolio, start=start, defaults=values
                    )
        if mismatches and not repair:
            portfolio.writes_blocked = True
            portfolio.save(update_fields=["writes_blocked"])
        # Repair alone never unblocks; an independent subsequent clean check may do so.
        if not mismatches:
            portfolio.writes_blocked = False
            portfolio.save(update_fields=["writes_blocked"])
        result = Reconciliation.objects.create(
            portfolio=portfolio, checked=len(set(expected) | set(actual)), mismatches=mismatches
        )
        JobStatus.objects.update_or_create(
            name="reconciliation",
            defaults={
                "last_success": timezone.now(),
                "last_error": "mismatch" if mismatches else "",
            },
        )
        return result
