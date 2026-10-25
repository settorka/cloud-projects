from decimal import Decimal
from datetime import timedelta, timezone as dt_timezone
from django.utils import timezone
from rest_framework import serializers
from .calendar import GB


class LegSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=3, min_value=Decimal("0.001"), max_value=Decimal("100000.000")
    )
    price = serializers.DecimalField(
        max_digits=12,
        decimal_places=4,
        min_value=Decimal("-100000.0000"),
        max_value=Decimal("100000.0000"),
    )

    def validate_start(self, value):
        value = value.astimezone(dt_timezone.utc)
        if value.minute not in (0, 30) or value.second or value.microsecond:
            raise serializers.ValidationError("Expected a half-hour UTC boundary")
        if value <= timezone.now():
            raise serializers.ValidationError("Delivery must be in the future")
        local_day = timezone.now().astimezone(GB).date()
        if value.astimezone(GB).date() > local_day + timedelta(days=7):
            raise serializers.ValidationError("Maximum delivery horizon is seven days")
        return value


class TradeSerializer(serializers.Serializer):
    portfolio = serializers.SlugField()
    counterparty = serializers.SlugField()
    direction = serializers.ChoiceField(choices=["BUY", "SELL"])
    legs = LegSerializer(many=True, allow_empty=False, max_length=50)
    reason = serializers.CharField(max_length=300)

    def validate_legs(self, value):
        if len({x["start"] for x in value}) != len(value):
            raise serializers.ValidationError("Duplicate intervals")
        if len({x["start"].astimezone(GB).date() for x in value}) != 1:
            raise serializers.ValidationError("One delivery day per booking")
        return sorted(value, key=lambda x: x["start"])


class AmendmentSerializer(TradeSerializer):
    expected_revision = serializers.IntegerField(min_value=1)


class CancellationSerializer(serializers.Serializer):
    expected_revision = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=300)


class LimitSerializer(serializers.Serializer):
    lower = serializers.DecimalField(max_digits=16, decimal_places=3)
    upper = serializers.DecimalField(max_digits=16, decimal_places=3)
    expected_revision = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=300)

    def validate(self, data):
        if data["lower"] > data["upper"]:
            raise serializers.ValidationError("lower exceeds upper")
        return data
