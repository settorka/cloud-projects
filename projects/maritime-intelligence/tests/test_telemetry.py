"""Trace propagation, low-cardinality metrics and sensitive-data exclusion."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from v1.api import create_app
from v1.telemetry import configure, traced


def providers():
    spans = InMemorySpanExporter()
    traces = TracerProvider()
    traces.add_span_processor(SimpleSpanProcessor(spans))
    reader = InMemoryMetricReader()
    meter = MeterProvider(metric_readers=[reader])
    return SimpleNamespace(traces=traces, meter=meter), spans, reader


def test_http_and_database_traces_exclude_credentials_and_identifiers(settings, monkeypatch):
    runtime, spans, reader = providers()
    monkeypatch.setattr(trace, "get_tracer", lambda name: runtime.traces.get_tracer(name))

    class Repository:
        @traced("postgres.latest")
        def latest(self, mmsi):
            return {"event_time": datetime.now(UTC), "mmsi": mmsi}

    client = TestClient(create_app(Repository(), settings, runtime))
    response = client.get(
        "/v1/vessels/230123456/latest?secret=do-not-export",
        headers={"Authorization": "Bearer " + settings.api_token},
    )
    assert response.status_code == 200
    finished = spans.get_finished_spans()
    server = next(s for s in finished if s.kind == trace.SpanKind.SERVER)
    database = next(s for s in finished if s.name == "postgres.latest")
    assert server.name == "GET /v1/vessels/{mmsi}/latest"
    assert database.context.trace_id == server.context.trace_id
    assert database.parent.span_id == server.context.span_id
    for span in finished:
        attributes = repr(dict(span.attributes))
        assert settings.api_token not in attributes
        assert "230123456" not in attributes and "do-not-export" not in attributes
    for resource in reader.get_metrics_data().resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                for point in metric.data.data_points:
                    assert "230123456" not in repr(dict(point.attributes))
    before = len(finished)
    assert client.get("/health/live").status_code == 200
    assert len(spans.get_finished_spans()) == before
    runtime.traces.shutdown()
    runtime.meter.shutdown()


def test_kafka_context_connects_publish_to_processing(settings, monkeypatch):
    from v1.adapters import kafka
    from v1.workers import process_message

    runtime, spans, _ = providers()
    monkeypatch.setattr(trace, "get_tracer", lambda name: runtime.traces.get_tracer(name))
    sent = []

    class Producer:
        def __init__(self, config):
            pass

        def produce(self, topic, key, value, on_delivery):
            sent.append(value)
            on_delivery(None, None)

        def flush(self, timeout):
            return 0

    monkeypatch.setattr(kafka, "Producer", Producer)
    now = datetime.now(UTC)
    event = {
        "topic": "vessels-v2/230123456/location",
        "received_at": now.isoformat(),
        "payload": json.dumps({"time": now.timestamp(), "lon": 24.5, "lat": 60.5}),
    }
    kafka.KafkaPublisher(settings).publish("230123456", event)

    class Message:
        def value(self):
            return sent[0]

    class Repository:
        def save(self, *args):
            return True

    committed = []

    class Consumer:
        def commit(self, **kwargs):
            committed.append(kwargs)

    process_message(Repository(), Consumer(), Message(), settings)
    finished = spans.get_finished_spans()
    producer = next(s for s in finished if s.kind == trace.SpanKind.PRODUCER)
    consumer = next(s for s in finished if s.kind == trace.SpanKind.CONSUMER)
    assert producer.context.trace_id == consumer.context.trace_id
    assert consumer.parent.span_id == producer.context.span_id
    assert len(committed) == 1
    assert all("230123456" not in repr(dict(s.attributes)) for s in finished)
    runtime.traces.shutdown()
    runtime.meter.shutdown()


def test_disabled_telemetry_does_not_create_exporters(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert configure("api") is None
