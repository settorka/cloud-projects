"""OpenTelemetry only: OTLP to a collector, without AWS SDK calls in the application."""

import functools
import logging
import math
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from opentelemetry import metrics, propagate, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import Observation
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased


@dataclass
class Telemetry:
    traces: TracerProvider
    meter: MeterProvider
    logs: LoggerProvider
    handler: LoggingHandler

    def shutdown(self):
        logging.getLogger().removeHandler(self.handler)
        self.logs.shutdown()
        self.meter.shutdown()
        self.traces.shutdown()


def configure(role):
    if os.environ["OTEL_SDK_DISABLED"].lower() == "true":
        return None
    ratio = float(os.environ["OTEL_TRACES_SAMPLER_ARG"])
    if not math.isfinite(ratio) or not 0 <= ratio <= 1:
        raise ValueError("OTEL_TRACES_SAMPLER_ARG must be between 0 and 1")
    endpoint = os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"].rstrip("/")
    timeout = float(os.environ["OTEL_EXPORT_TIMEOUT_SECONDS"])
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("OTEL_EXPORT_TIMEOUT_SECONDS must be positive")
    resource = Resource.create(
        {
            "service.name": os.environ["OTEL_SERVICE_NAME"] + "-" + role,
            "deployment.environment.name": os.environ["OTEL_DEPLOYMENT_ENVIRONMENT"],
            "Project": os.environ["OTEL_PROJECT_NAME"],
        }
    )
    traces = TracerProvider(
        resource=resource,
        id_generator=AwsXRayIdGenerator(),
        sampler=ParentBased(TraceIdRatioBased(ratio)),
    )
    traces.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint + "/v1/traces", timeout=timeout))
    )
    meter = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=endpoint + "/v1/metrics", timeout=timeout)
            )
        ],
    )
    logs = LoggerProvider(resource=resource)
    logs.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint + "/v1/logs", timeout=timeout))
    )
    handler = LoggingHandler(level=logging.INFO, logger_provider=logs)
    handler.addFilter(
        lambda record: not record.name.startswith(("opentelemetry", "urllib3", "botocore", "boto3"))
    )
    logging.getLogger().addHandler(handler)
    trace.set_tracer_provider(traces)
    metrics.set_meter_provider(meter)
    if role == "api" and os.environ["OTEL_DEPLOYMENT_ENVIRONMENT"] == "aws":
        marker = Path(os.environ["OTEL_BACKUP_MARKER_PATH"])

        def age(_):
            hours = max(0, time.time() - marker.stat().st_mtime) / 3600 if marker.exists() else 999
            return [Observation(hours)]

        meter.get_meter("maritime").create_observable_gauge(
            "BackupAgeHours", callbacks=[age], unit="1"
        )
    return Telemetry(traces, meter, logs, handler)


def traced(name):
    """Deliberately excludes SQL, parameters, credentials and vessel identifiers."""

    def decorate(function):
        @functools.wraps(function)
        def call(*args, **kwargs):
            with operation(name, kind=trace.SpanKind.CLIENT):
                return function(*args, **kwargs)

        return call

    return decorate


def publish_context():
    carrier = {}
    propagate.inject(carrier)
    return carrier


@contextmanager
def operation(name, *, tracer=None, **kwargs):
    # Database exceptions can contain row values. Export exception type, never text.
    tracer = tracer or trace.get_tracer("maritime")
    kwargs.update(record_exception=False, set_status_on_exception=False)
    with tracer.start_as_current_span(name, **kwargs) as active:
        try:
            yield active
        except Exception as error:
            active.set_status(trace.Status(trace.StatusCode.ERROR))
            active.set_attribute("error.type", type(error).__name__)
            raise
