import json
import logging
import os
import uuid
from pathlib import Path
import boto3
from botocore.config import Config
from django.db import transaction, close_old_connections
from django.utils import timezone
from jsonschema import Draft202012Validator
from .models import Outbox, Inbox, ConsumerGuard
from .observability import EVENTS

SCHEMA = json.loads((Path(__file__).parent / "event.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=Draft202012Validator.FORMAT_CHECKER)


def validate(envelope):
    VALIDATOR.validate(envelope)
    if envelope["schema_version"] != 1:
        raise ValueError("Unsupported event schema")


def emit(event_type, entity_id, revision, data, destinations):
    envelope = {
        "event_id": str(uuid.uuid4()),
        "schema_version": 1,
        "type": event_type,
        "entity_id": str(entity_id),
        "revision": revision,
        "occurred_at": timezone.now().isoformat(),
        "data": data,
    }
    validate(envelope)
    for destination in destinations:
        Outbox.objects.create(destination=destination, envelope=envelope)


def sqs():
    return boto3.client(
        "sqs",
        endpoint_url=os.getenv("SQS_ENDPOINT_URL"),
        region_name=os.getenv("AWS_DEFAULT_REGION", "eu-north-1"),
        config=Config(connect_timeout=3, read_timeout=25, retries={"max_attempts": 2}),
    )


def queue_url(client, name):
    return client.get_queue_url(QueueName=name)["QueueUrl"]


def publish_once(client=None, limit=20):
    client = client or sqs()
    count = 0
    for pk in (
        Outbox.objects.filter(published_at__isnull=True)
        .order_by("created_at")
        .values_list("pk", flat=True)[:limit]
    ):
        with transaction.atomic():
            item = (
                Outbox.objects.select_for_update(skip_locked=True)
                .filter(pk=pk, published_at__isnull=True)
                .first()
            )
            if item is None:
                continue
            item.attempts += 1
            try:
                client.send_message(
                    QueueUrl=queue_url(client, item.destination),
                    MessageBody=json.dumps(item.envelope),
                )
            except Exception as exc:
                item.last_error = type(exc).__name__
                item.save(update_fields=["attempts", "last_error"])
                logging.getLogger(__name__).exception(
                    "outbox_delivery_failed", extra={"event_id": str(item.envelope["event_id"])}
                )
                continue
            item.published_at = timezone.now()
            item.last_error = ""
            item.save(update_fields=["published_at", "attempts", "last_error"])
            count += 1
    return count


def apply_event(envelope):
    validate(envelope)
    from .domain import handle_event

    with transaction.atomic():
        # A persisted guard also serializes first-row creation and duplicate deliveries.
        ConsumerGuard.objects.select_for_update().get(name="events")
        if Inbox.objects.filter(event_id=envelope["event_id"]).exists():
            EVENTS.labels("duplicate").inc()
            return False
        handle_event(envelope)
        Inbox.objects.create(event_id=envelope["event_id"])
    EVENTS.labels("applied").inc()
    return True


def process_message(message, queue, client):
    close_old_connections()
    try:
        apply_event(json.loads(message["Body"]))
        client.delete_message(QueueUrl=queue, ReceiptHandle=message["ReceiptHandle"])
        return True
    except Exception:
        EVENTS.labels("failed").inc()
        logging.getLogger(__name__).exception("event_processing_failed")
        return False
    finally:
        close_old_connections()
