from jsonschema.exceptions import ValidationError as SchemaValidationError
import uuid
from unittest.mock import Mock
import pytest
from django.utils import timezone
from app.events import validate, publish_once
from app.models import Outbox
from rest_framework.test import APIClient


def envelope():
    return {
        "event_id": str(uuid.uuid4()),
        "schema_version": 1,
        "type": "price.updated",
        "entity_id": "price",
        "revision": 1,
        "occurred_at": timezone.now().isoformat(),
        "data": {},
    }


def test_contract_rejects_unknown_version():
    value = envelope()
    value["schema_version"] = 2
    with pytest.raises(SchemaValidationError):
        validate(value)


@pytest.mark.django_db
def test_outbox_failure_and_retry():
    row = Outbox.objects.create(destination="valuation-input", envelope=envelope())
    client = Mock()
    client.get_queue_url.return_value = {"QueueUrl": "local"}
    client.send_message.side_effect = RuntimeError("offline")
    assert publish_once(client) == 0
    row.refresh_from_db()
    assert row.published_at is None and row.attempts == 1
    client.send_message.side_effect = None
    assert publish_once(client) == 1
    row.refresh_from_db()
    assert row.published_at is not None


@pytest.mark.django_db
def test_metrics_requires_authentication():
    client = APIClient()
    assert client.get("/metrics").status_code == 401
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200


@pytest.mark.django_db
def test_operator_replay_is_bounded_and_explicit():
    from django.core.management import call_command
    from django.core.management.base import CommandError

    row = Outbox.objects.create(
        destination="valuation-input", envelope=envelope(), published_at=timezone.now()
    )
    with pytest.raises(CommandError):
        call_command(
            "replay_outbox",
            destination="valuation-input",
            since="2026-01-01T00:00:00Z",
            limit=1,
            confirm=False,
        )
    call_command(
        "replay_outbox",
        destination="valuation-input",
        since="2026-01-01T00:00:00Z",
        limit=1,
        confirm=True,
    )
    row.refresh_from_db()
    assert row.published_at is None and row.last_error == "operator_replay"
