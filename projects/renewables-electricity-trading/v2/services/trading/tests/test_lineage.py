import json
import uuid
from unittest.mock import Mock
import pytest
from django.utils import timezone
from app import events, telemetry
from app.models import ConsumerGuard, Inbox, Outbox, ProcessExecution
from app.processes import begin, move
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry import trace

EXPORTER = InMemorySpanExporter()
PROVIDER = TracerProvider()
PROVIDER.add_span_processor(SimpleSpanProcessor(EXPORTER))
trace.set_tracer_provider(PROVIDER)


def envelope():
    return {
        "event_id": str(uuid.uuid4()),
        "schema_version": 1,
        "type": "price.updated",
        "entity_id": "test",
        "revision": 1,
        "occurred_at": timezone.now().isoformat(),
        "data": {},
    }


def message(value):
    return {"Body": json.dumps(value), "ReceiptHandle": "receipt", "MessageId": str(uuid.uuid4())}


@pytest.mark.django_db(transaction=True)
def test_trace_continues_through_outbox_and_consumer(monkeypatch):
    monkeypatch.setenv("EVENT_TRANSPORT", "sqs")
    monkeypatch.setenv("OTEL_ENABLED", "false")
    ConsumerGuard.objects.create(name="events")
    monkeypatch.setattr("app.domain.handle_event", lambda _: None)
    EXPORTER.clear()
    with telemetry.span("booking"):
        events.emit("price.updated", "test", 1, {}, ["valuation-input"])
    client = Mock()
    client.get_queue_url.return_value = {"QueueUrl": "queue"}
    assert events.publish_once(client) == 1
    sent = json.loads(client.send_message.call_args.kwargs["MessageBody"])
    assert events.process_message(message(sent), "queue", client)
    spans = EXPORTER.get_finished_spans()
    booking = next(s for s in spans if s.name == "booking")
    publish = next(s for s in spans if s.name == "outbox.publish")
    consume = next(s for s in spans if s.name == "event.consume")
    assert booking.context.trace_id == publish.context.trace_id == consume.context.trace_id
    assert publish.parent.span_id == booking.context.span_id
    assert consume.parent.span_id == publish.context.span_id
    run = ProcessExecution.objects.get(kind="consume")
    assert run.trace_id == format(booking.context.trace_id, "032x")
    assert list(run.transitions.values_list("state", flat=True).order_by("sequence")) == [
        "CREATED",
        "VALIDATED",
        "APPLYING",
        "APPLIED",
        "ACKNOWLEDGED",
    ]


@pytest.mark.django_db(transaction=True)
def test_ack_failure_redelivery_is_durable_and_does_not_reapply(monkeypatch):
    ConsumerGuard.objects.create(name="events")
    handle = Mock()
    monkeypatch.setattr("app.domain.handle_event", handle)
    client = Mock()
    client.delete_message.side_effect = RuntimeError("offline")
    value = envelope()
    assert not events.process_message(message(value), "queue", client)
    assert ProcessExecution.objects.get().state == "ACK_FAILED"
    assert Inbox.objects.filter(event_id=value["event_id"]).exists()
    client.delete_message.side_effect = None
    assert events.process_message(message(value), "queue", client)
    assert handle.call_count == 1
    assert ProcessExecution.objects.filter(state="ACKNOWLEDGED").count() == 1
    assert ProcessExecution.objects.filter(transitions__state="DUPLICATE").exists()


@pytest.mark.django_db(transaction=True)
def test_business_failure_rolls_back_inbox_and_applied_states(monkeypatch):
    ConsumerGuard.objects.create(name="events")
    monkeypatch.setattr("app.domain.handle_event", Mock(side_effect=ValueError("invalid")))
    client = Mock()
    assert not events.process_message(message(envelope()), "queue", client)
    assert not Inbox.objects.exists()
    run = ProcessExecution.objects.get()
    assert run.state == "FAILED"
    assert not run.transitions.filter(state__in=["APPLYING", "APPLIED"]).exists()
    client.delete_message.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_invalid_event_is_audited_without_acknowledgement():
    client = Mock()
    assert not events.process_message(message({"secret": "must-not-store"}), "queue", client)
    run = ProcessExecution.objects.get()
    assert run.state == "FAILED" and run.error_code == "ValidationError"
    client.delete_message.assert_not_called()


@pytest.mark.django_db
def test_illegal_transition_rejected_without_mutation():
    run = begin("consume", "test")
    with pytest.raises(ValueError):
        move(run, "ACKNOWLEDGED")
    run.refresh_from_db()
    assert run.state == "CREATED" and run.transitions.count() == 1


@pytest.mark.django_db
def test_eventbridge_partial_failure_keeps_outbox_pending(monkeypatch):
    monkeypatch.setenv("EVENT_TRANSPORT", "eventbridge")
    monkeypatch.setenv("EVENT_BUS_NAME", "test-bus")
    monkeypatch.setenv("QUEUE_PREFIX", "renewables-v2-dev-")
    bus = Mock()
    bus.put_events.return_value = {"FailedEntryCount": 1}
    monkeypatch.setattr(events.boto3, "client", lambda *a, **k: bus)
    row = Outbox.objects.create(destination="valuation-input", envelope=envelope())
    assert events.publish_once(Mock()) == 0
    row.refresh_from_db()
    assert row.published_at is None
    assert ProcessExecution.objects.get().state == "FAILED"
    bus.put_events.return_value = {"FailedEntryCount": 0}
    assert events.publish_once(Mock()) == 1
    detail = json.loads(bus.put_events.call_args.kwargs["Entries"][0]["Detail"])
    assert detail["destination"] == "renewables-v2-dev-valuation-input"
    assert "trace_context" in detail["envelope"]


@pytest.mark.django_db(transaction=True)
def test_unsampled_event_still_has_durable_lineage(monkeypatch):
    ConsumerGuard.objects.create(name="events")
    monkeypatch.setattr("app.domain.handle_event", lambda _: None)
    value = envelope()
    value["trace_context"] = {
        "traceparent": "00-12345678901234567890123456789012-1234567890123456-00"
    }
    EXPORTER.clear()
    assert events.process_message(message(value), "queue", Mock())
    run = ProcessExecution.objects.get()
    assert run.state == "ACKNOWLEDGED" and run.trace_id == "12345678901234567890123456789012"
    assert not EXPORTER.get_finished_spans()


@pytest.mark.django_db
def test_process_pruning_retains_recent_unfinished_and_business_records():
    from datetime import timedelta
    from django.core.management import call_command
    from django.core.management.base import CommandError

    old = begin("consume", "old")
    move(old, "FAILED", "ValueError")
    interrupted = begin("consume", "interrupted")
    recent = begin("consume", "recent")
    move(recent, "FAILED", "ValueError")
    ProcessExecution.objects.filter(pk__in=[old.pk, interrupted.pk]).update(
        updated_at=timezone.now() - timedelta(days=8)
    )
    inbox = Inbox.objects.create(event_id=uuid.uuid4())
    with pytest.raises(CommandError):
        call_command("process_history", prune_days=7, confirm=False)
    call_command("process_history", prune_days=7, limit=1, confirm=True)
    assert not ProcessExecution.objects.filter(pk=old.pk).exists()
    assert ProcessExecution.objects.filter(pk__in=[recent.pk, interrupted.pk]).count() == 2
    assert Inbox.objects.filter(pk=inbox.pk).exists()
