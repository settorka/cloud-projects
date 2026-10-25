from decimal import Decimal, ROUND_HALF_EVEN
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .models import ConsumerGuard, TradeCopy, Price, PortfolioAccess, ValuationRun, JobStatus
from .common import Forbidden


def seed_domain():
    from django.contrib.auth.models import User

    for user in User.objects.filter(username__in=["trader", "risk", "viewer"]):
        PortfolioAccess.objects.get_or_create(user=user, portfolio="demo")


def handle_event(event):
    data = event["data"]
    if event["type"] == "trade.changed":
        import uuid

        if (
            str(uuid.UUID(data["id"])) != event["entity_id"]
            or data["revision"] != event["revision"]
        ):
            raise ValueError("Trade identity/revision mismatch")
        if (
            data["direction"] not in ["BUY", "SELL"]
            or data["state"] not in ["ACTIVE", "CANCELLED"]
            or not data["portfolio"]
            or len(data["legs"]) > 50
        ):
            raise ValueError("Invalid trade snapshot")
        seen = set()
        for leg in data["legs"]:
            start = parse_datetime(leg["start"])
            q = Decimal(leg["quantity"])
            p = Decimal(leg["price"])
            if (
                not start
                or not start.tzinfo
                or start in seen
                or not q.is_finite()
                or q <= 0
                or not p.is_finite()
            ):
                raise ValueError("Invalid trade leg")
            seen.add(start)
        current = TradeCopy.objects.filter(pk=data["id"]).first()
        if current and current.revision >= event["revision"]:
            return
        if current and current.portfolio != data["portfolio"]:
            raise ValueError("Trade portfolio cannot change")
        TradeCopy.objects.update_or_create(
            pk=data["id"],
            defaults={
                "revision": event["revision"],
                "portfolio": data["portfolio"],
                "snapshot": data,
            },
        )
    elif event["type"] == "price.updated":
        start = parse_datetime(data["start"])
        published = parse_datetime(data["published_at"])
        valid = parse_datetime(data["valid_until"])
        value = Decimal(data["quantity"])
        if (
            not start
            or not start.tzinfo
            or not published
            or not published.tzinfo
            or not valid
            or valid <= published
            or not value.is_finite()
        ):
            raise ValueError("Invalid price")
        current = Price.objects.filter(start=start).first()
        if current and current.revision >= event["revision"]:
            return
        Price.objects.update_or_create(
            start=start,
            defaults={
                "revision": event["revision"],
                "value": value,
                "published_at": published,
                "valid_until": valid,
            },
        )
    else:
        raise ValueError("Unsupported Valuation event")
    JobStatus.objects.update_or_create(
        name="input_application", defaults={"last_success": timezone.now(), "last_error": ""}
    )
    portfolios = (
        [data["portfolio"]]
        if event["type"] == "trade.changed"
        else list(TradeCopy.objects.values_list("portfolio", flat=True).distinct())
    )
    for portfolio in portfolios:
        calculate(portfolio)


@transaction.atomic
def calculate(portfolio):
    # Shared with input application, so one run observes a coherent local snapshot.
    ConsumerGuard.objects.select_for_update().get(name="events")
    total = Decimal("0")
    results = []
    versions = {
        "trades": {},
        "prices": {},
        "method": "undiscounted-fixed-price-v1",
        "rounding": "HALF_EVEN_PER_LEG",
    }
    missing = False
    stale = False
    for trade in TradeCopy.objects.filter(portfolio=portfolio).order_by("id"):
        versions["trades"][str(trade.pk)] = trade.revision
        if trade.snapshot["state"] == "CANCELLED":
            continue
        for leg in trade.snapshot["legs"]:
            start = parse_datetime(leg["start"])
            price = Price.objects.filter(start=start).first()
            row = {
                "trade": str(trade.pk),
                "revision": trade.revision,
                "start": leg["start"],
                "quantity": leg["quantity"],
                "contract_price": leg["price"],
                "direction": trade.snapshot["direction"],
            }
            if not price:
                row["state"] = "MISSING_PRICE"
                missing = True
            else:
                versions["prices"][price.start.isoformat()] = {
                    "revision": price.revision,
                    "value": str(price.value),
                    "published_at": price.published_at.isoformat(),
                    "valid_until": price.valid_until.isoformat(),
                }
                value = (
                    Decimal(leg["quantity"])
                    * (price.value - Decimal(leg["price"]))
                    * (1 if trade.snapshot["direction"] == "BUY" else -1)
                )
                value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
                total += value
                row.update(
                    {
                        "value": str(value),
                        "mark": str(price.value),
                        "state": "STALE" if price.valid_until <= timezone.now() else "CURRENT",
                    }
                )
                stale = stale or price.valid_until <= timezone.now()
            results.append(row)
    state = "INCOMPLETE" if missing else "STALE" if stale else "CURRENT"
    run = ValuationRun.objects.create(
        portfolio=portfolio,
        state=state,
        total=None if missing else total,
        results=results,
        input_versions=versions,
    )
    JobStatus.objects.update_or_create(
        name="valuation", defaults={"last_success": timezone.now(), "last_error": ""}
    )
    return run


def require_access(user, portfolio):
    if not PortfolioAccess.objects.filter(user=user, portfolio=portfolio).exists():
        raise Forbidden()
