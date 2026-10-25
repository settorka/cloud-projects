from django.conf import settings
import uuid
from django.db import models


class Outbox(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    destination = models.CharField(max_length=100)
    envelope = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True)

    class Meta:
        indexes = [models.Index(fields=["published_at", "created_at"])]


class Inbox(models.Model):
    event_id = models.UUIDField(primary_key=True)
    applied_at = models.DateTimeField(auto_now_add=True)


class JobStatus(models.Model):
    name = models.CharField(max_length=80, primary_key=True)
    last_success = models.DateTimeField(null=True)
    last_error = models.CharField(max_length=300, blank=True)


class ConsumerGuard(models.Model):
    name = models.CharField(max_length=80, primary_key=True)


class Portfolio(models.Model):
    id = models.SlugField(primary_key=True)
    name = models.CharField(max_length=100)
    lower_limit = models.DecimalField(max_digits=16, decimal_places=3, default=-20)
    upper_limit = models.DecimalField(max_digits=16, decimal_places=3, default=200)
    limit_revision = models.PositiveIntegerField(default=1)
    writes_blocked = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(lower_limit__lte=models.F("upper_limit")), name="ordered_limits"
            )
        ]


class Membership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE)
    role = models.CharField(
        max_length=10, choices=[("trader", "trader"), ("risk", "risk"), ("viewer", "viewer")]
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "portfolio"], name="one_membership")]


class Counterparty(models.Model):
    id = models.SlugField(primary_key=True)
    name = models.CharField(max_length=100)


class Asset(models.Model):
    id = models.SlugField(primary_key=True)
    portfolio = models.ForeignKey(Portfolio, on_delete=models.PROTECT)
    technology = models.CharField(max_length=10, choices=[("wind", "wind"), ("solar", "solar")])
    capacity_mw = models.DecimalField(max_digits=12, decimal_places=3)


class Position(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.PROTECT)
    start = models.DateTimeField()
    purchases = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    sales = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    forecast = models.DecimalField(max_digits=18, decimal_places=3, null=True)
    forecast_revision = models.PositiveIntegerField(default=0)
    forecast_published_at = models.DateTimeField(null=True)
    forecast_valid_until = models.DateTimeField(null=True)
    meter = models.DecimalField(max_digits=18, decimal_places=3, null=True)
    meter_revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["portfolio", "start"], name="one_position"),
            models.CheckConstraint(
                condition=models.Q(purchases__gte=0, sales__gte=0), name="positive_gross_position"
            ),
        ]


class Trade(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(Portfolio, on_delete=models.PROTECT)
    counterparty = models.ForeignKey(Counterparty, on_delete=models.PROTECT)
    direction = models.CharField(max_length=4, choices=[("BUY", "BUY"), ("SELL", "SELL")])
    revision = models.PositiveIntegerField(default=1)
    state = models.CharField(max_length=10, default="ACTIVE")
    created_at = models.DateTimeField(auto_now_add=True)


class TradeRevision(models.Model):
    trade = models.ForeignKey(Trade, on_delete=models.PROTECT)
    number = models.PositiveIntegerField()
    snapshot = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["trade", "number"], name="one_trade_revision")
        ]


class TradeLeg(models.Model):
    revision = models.ForeignKey(TradeRevision, on_delete=models.PROTECT, related_name="legs")
    start = models.DateTimeField()
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    price = models.DecimalField(max_digits=12, decimal_places=4)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["revision", "start"], name="one_revision_leg"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="positive_quantity"),
        ]


class Decision(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    key = models.CharField(max_length=100)
    fingerprint = models.CharField(max_length=64)
    http_status = models.PositiveIntegerField()
    response = models.JSONField()
    inputs = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "key"], name="unique_request_key")]


class Audit(models.Model):
    actor = models.CharField(max_length=150)
    action = models.CharField(max_length=60)
    portfolio = models.ForeignKey(Portfolio, on_delete=models.PROTECT)
    details = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class Reconciliation(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.PROTECT)
    checked = models.PositiveIntegerField()
    mismatches = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
