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
from .configuration import integer
from .telemetry import span, carrier
from .processes import begin, move
from opentelemetry.trace import SpanKind

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
    envelope["trace_context"] = carrier()
    validate(envelope)
    for destination in destinations:
        Outbox.objects.create(destination=destination, envelope=envelope)


def sqs():
    return boto3.client(
        "sqs",
        endpoint_url=os.getenv("SQS_ENDPOINT_URL") or None,
        region_name=os.environ["AWS_DEFAULT_REGION"],
        config=Config(
            connect_timeout=integer("SDK_CONNECT_TIMEOUT_SECONDS"),
            read_timeout=integer("SQS_READ_TIMEOUT_SECONDS"),
            retries={"total_max_attempts": integer("SQS_SDK_ATTEMPTS", 1, 3)},
        ),
    )


def queue_url(client, name):
    return client.get_queue_url(QueueName=name)["QueueUrl"]


def publish_once(client=None, limit=None):
    limit = limit if limit is not None else integer("OUTBOX_BATCH_SIZE", 1, 100)
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
            with span(
                "outbox.publish",
                kind=SpanKind.PRODUCER,
                parent=item.envelope.get("trace_context", {}),
                attributes={"messaging.message.id": item.envelope["event_id"]},
            ):
                run = begin("publish", item.envelope["event_id"], item.destination, item.envelope)
                move(run, "PUBLISHING")
                try:
                    deliver(client, item)
                except Exception as exc:
                    move(run, "FAILED", type(exc).__name__)
                    item.last_error = type(exc).__name__
                    item.save(update_fields=["attempts", "last_error"])
                    logging.getLogger(__name__).error(
                        "outbox_delivery_failed",
                        extra={
                            "event_id": item.envelope["event_id"],
                            "error_code": type(exc).__name__,
                        },
                    )
                    continue
                move(run, "PUBLISHED")
            item.published_at = timezone.now()
            item.last_error = ""
            item.save(update_fields=["published_at", "attempts", "last_error"])
            count += 1
    return count


def deliver(client, item):
    envelope = {**item.envelope, "trace_context": carrier()}
    if os.environ["EVENT_TRANSPORT"] == "eventbridge":
        bus = boto3.client(
            "events",
            region_name=os.environ["AWS_DEFAULT_REGION"],
            config=Config(
                connect_timeout=integer("SDK_CONNECT_TIMEOUT_SECONDS"),
                read_timeout=integer("EVENTBRIDGE_READ_TIMEOUT_SECONDS"),
                retries={"max_attempts": integer("EVENTBRIDGE_SDK_RETRIES", 0, 3)},
            ),
        )
        result = bus.put_events(
            Entries=[
                {
                    "EventBusName": os.environ["EVENT_BUS_NAME"],
                    "Source": "renewables.v2",
                    "DetailType": envelope["type"],
                    "Detail": json.dumps(
                        {
                            "destination": os.environ["QUEUE_PREFIX"] + item.destination,
                            "envelope": envelope,
                        }
                    ),
                }
            ]
        )
        if result.get("FailedEntryCount", 0):
            raise RuntimeError("EventBridgeRejected")
    else:
        client.send_message(
            QueueUrl=queue_url(client, item.destination), MessageBody=json.dumps(envelope)
        )


def apply_event(envelope, run=None):
    validate(envelope)
    from .domain import handle_event

    with transaction.atomic():
        # A persisted guard also serializes first-row creation and duplicate deliveries.
        ConsumerGuard.objects.select_for_update().get(name="events")
        if run:
            move(run, "APPLYING")
        if Inbox.objects.filter(event_id=envelope["event_id"]).exists():
            if run:
                move(run, "DUPLICATE")
            EVENTS.labels("duplicate").inc()
            return False
        handle_event(envelope)
        Inbox.objects.create(event_id=envelope["event_id"])
        if run:
            move(run, "APPLIED")
    EVENTS.labels("applied").inc()
    return True


def process_message(message, queue, client):
    close_old_connections()
    run = None
    try:
        raw = message["Body"]
        if len(raw.encode()) > 262144:
            raise ValueError("Event exceeds 256 KiB")
        envelope = json.loads(raw)
        validate(envelope)
        with span(
            "event.consume",
            kind=SpanKind.CONSUMER,
            parent=envelope.get("trace_context", {}),
            attributes={"messaging.message.id": envelope["event_id"]},
        ):
            run = begin("consume", envelope["event_id"], queue, envelope)
            move(run, "VALIDATED")
            try:
                apply_event(envelope, run)
            except Exception as exc:
                # APPLYING and business changes rolled back together.
                run.refresh_from_db()
                move(run, "FAILED", type(exc).__name__)
                raise
            try:
                client.delete_message(QueueUrl=queue, ReceiptHandle=message["ReceiptHandle"])
            except Exception as exc:
                move(run, "ACK_FAILED", type(exc).__name__)
                raise
            move(run, "ACKNOWLEDGED")
        return True
    except Exception as exc:
        if run is None:
            # Invalid payloads also have durable attempt history, without storing the payload.
            run = begin("consume", message.get("MessageId", "invalid"))
            move(run, "FAILED", type(exc).__name__)
        EVENTS.labels("failed").inc()
        logging.getLogger(__name__).error(
            "event_processing_failed",
            extra={
                "process_id": str(run.pk),
                "error_code": type(exc).__name__,
            },
        )
        return False
    finally:
        close_old_connections()
