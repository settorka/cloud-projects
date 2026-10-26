"""Explicit, bounded OTLP tracing; no request bodies, SQL text or baggage export."""

import atexit
import os
import threading
from contextlib import contextmanager
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_lock = threading.Lock()
_configured = False
propagator = TraceContextTextMapPropagator()


def configure():
    global _configured
    with _lock:
        if _configured:
            return
        if os.environ["OTEL_ENABLED"].lower() != "true":
            return
        from django.conf import settings
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        ratio = float(os.environ["OTEL_TRACES_SAMPLER_ARG"])
        if not 0 <= ratio <= 1:
            raise ValueError("OTEL_TRACES_SAMPLER_ARG must be 0..1")
        provider = TracerProvider(
            id_generator=AwsXRayIdGenerator(),
            resource=Resource.create(
                {
                    "service.name": settings.SERVICE,
                    "service.version": os.environ["APP_VERSION"],
                    "deployment.environment.name": os.environ["DEPLOYMENT_ENVIRONMENT"],
                }
            ),
            # Local ratio is enforced even when external callers request sampling.
            sampler=TraceIdRatioBased(ratio),
        )
        endpoint = os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=endpoint.rstrip("/") + "/v1/traces",
                    timeout=int(os.environ["OTEL_EXPORT_TIMEOUT_SECONDS"]),
                ),
                max_queue_size=int(os.environ["OTEL_MAX_QUEUE_SIZE"]),
                max_export_batch_size=int(os.environ["OTEL_MAX_EXPORT_BATCH_SIZE"]),
                schedule_delay_millis=int(os.environ["OTEL_EXPORT_DELAY_MS"]),
            )
        )
        trace.set_tracer_provider(provider)
        atexit.register(provider.shutdown)
        _configured = True


def carrier():
    value = {}
    propagator.inject(value)
    return {k: v for k, v in value.items() if k in ("traceparent", "tracestate")}


def identifiers():
    ctx = trace.get_current_span().get_span_context()
    return (
        {"trace_id": format(ctx.trace_id, "032x"), "span_id": format(ctx.span_id, "016x")}
        if ctx.is_valid
        else {}
    )


@contextmanager
def span(name, kind=SpanKind.INTERNAL, parent=None, attributes=None):
    configure()
    context = propagator.extract(parent) if parent is not None else None
    with trace.get_tracer("renewables.v2").start_as_current_span(
        name,
        context=context,
        kind=kind,
        attributes=attributes or {},
        record_exception=False,
        set_status_on_exception=False,
    ) as current:
        try:
            yield current
        except Exception as exc:
            # Exception messages may contain financial data; export type only.
            current.set_attribute("error.type", type(exc).__name__)
            current.set_status(Status(StatusCode.ERROR))
            raise
