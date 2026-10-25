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


class TradeCopy(models.Model):
    id = models.UUIDField(primary_key=True)
    revision = models.PositiveIntegerField()
    portfolio = models.CharField(max_length=80)
    snapshot = models.JSONField()


class Price(models.Model):
    start = models.DateTimeField(unique=True)
    revision = models.PositiveIntegerField()
    value = models.DecimalField(max_digits=18, decimal_places=4)
    published_at = models.DateTimeField()
    valid_until = models.DateTimeField()


class PortfolioAccess(models.Model):
    user = models.ForeignKey("auth.User", on_delete=models.CASCADE)
    portfolio = models.CharField(max_length=80)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "portfolio"], name="one_valuation_access")
        ]


class ValuationRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.CharField(max_length=80)
    state = models.CharField(max_length=20)
    total = models.DecimalField(max_digits=24, decimal_places=2, null=True)
    results = models.JSONField()
    input_versions = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
