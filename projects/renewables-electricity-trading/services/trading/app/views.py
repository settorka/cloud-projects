from datetime import timedelta
from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Portfolio, Position, Trade, TradeRevision, Audit, Membership
from .serializers import (
    TradeSerializer,
    AmendmentSerializer,
    CancellationSerializer,
    LimitSerializer,
)
from .domain import book, membership, locked_portfolio, distance, replay_decision
from .common import Conflict
from .calendar import interval_identity


@api_view(["POST"])
def trades(request):
    return mutate(request, TradeSerializer)


def mutate(request, serializer_class, trade_id=None, cancel=False):
    if int(request.META.get("CONTENT_LENGTH") or 0) > 65536:
        return Response({"code": "payload_too_large"}, status=413)
    prior = replay_decision(
        request.user, request.headers.get("Idempotency-Key"), request.data, trade_id, cancel
    )
    if prior:
        response = Response(prior.response, status=prior.http_status)
        response["Idempotent-Replay"] = "true"
        return response
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    body, status, replay = book(
        request.user,
        request.headers.get("Idempotency-Key"),
        request.data,
        serializer.validated_data,
        trade_id,
        cancel,
    )
    response = Response(body, status=status)
    response["Idempotent-Replay"] = str(replay).lower()
    return response


@api_view(["POST"])
def amendments(request, trade_id):
    return mutate(request, AmendmentSerializer, trade_id)


@api_view(["POST"])
def cancellations(request, trade_id):
    return mutate(request, CancellationSerializer, trade_id, True)


@api_view(["GET"])
def trade_detail(request, trade_id):
    trade = get_object_or_404(Trade, pk=trade_id)
    membership(request.user, trade.portfolio_id)
    return Response(
        {
            "trade": TradeRevision.objects.get(trade=trade, number=trade.revision).snapshot,
            "history": list(
                TradeRevision.objects.filter(trade=trade).values(
                    "number", "reason", "created_at", "actor__username"
                )
            ),
        }
    )


@api_view(["GET"])
def portfolios(request):
    ids = Membership.objects.filter(user=request.user).values_list("portfolio_id", flat=True)
    return Response(list(Portfolio.objects.filter(pk__in=ids).values()))


@api_view(["GET"])
def positions(request, portfolio_id):
    membership(request.user, portfolio_id)
    portfolio = get_object_or_404(Portfolio, pk=portfolio_id)
    try:
        limit = min(100, max(1, int(request.query_params.get("limit", 100))))
        offset = max(0, int(request.query_params.get("offset", 0)))
    except ValueError:
        return Response({"detail": "Invalid pagination"}, status=400)
    query = Position.objects.filter(portfolio_id=portfolio_id).order_by("start")
    result = []
    for p in query[offset : offset + limit]:
        exposure = None if p.forecast is None else p.forecast + p.purchases - p.sales
        result.append(
            {
                "start": p.start,
                "end": p.start + timedelta(minutes=30),
                **interval_identity(p.start),
                "purchases": p.purchases,
                "sales": p.sales,
                "forecast": p.forecast,
                "forecast_revision": p.forecast_revision,
                "forecast_valid_until": p.forecast_valid_until,
                "stale": p.forecast_valid_until is None or p.forecast_valid_until <= timezone.now(),
                "expected_exposure": exposure,
                "breach": None if exposure is None else distance(exposure, portfolio) > 0,
                "actual_generation": p.meter,
                "actual_exposure": None if p.meter is None else p.meter + p.purchases - p.sales,
            }
        )
    return Response(
        {"count": query.count(), "offset": offset, "results": result, "as_of": timezone.now()}
    )


@api_view(["GET"])
def breaches(request, portfolio_id):
    membership(request.user, portfolio_id)
    p = get_object_or_404(Portfolio, pk=portfolio_id)
    rows = Position.objects.filter(portfolio=p, forecast__isnull=False).annotate(
        exposure=F("forecast") + F("purchases") - F("sales")
    )
    rows = rows.filter(Q(exposure__lt=p.lower_limit) | Q(exposure__gt=p.upper_limit))
    return Response(
        {
            "count": rows.count(),
            "results": list(
                rows.order_by("start").values("start", "exposure", "forecast_revision")[:100]
            ),
        }
    )


@api_view(["PUT"])
def limits(request, portfolio_id):
    membership(request.user, portfolio_id, risk=True)
    s = LimitSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    d = s.validated_data
    with transaction.atomic():
        p = locked_portfolio(portfolio_id)
        if p.limit_revision != d["expected_revision"]:
            raise Conflict("Stale limit revision")
        p.lower_limit = d["lower"]
        p.upper_limit = d["upper"]
        p.limit_revision += 1
        p.save()
        Audit.objects.create(
            actor=request.user.username,
            action="limits.changed",
            portfolio=p,
            details={
                "lower": str(d["lower"]),
                "upper": str(d["upper"]),
                "revision": p.limit_revision,
                "reason": d["reason"],
            },
        )
    return Response({"revision": p.limit_revision})
