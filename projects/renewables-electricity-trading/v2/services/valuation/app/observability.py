import json
import logging
import time
import uuid
from datetime import datetime, timezone
from prometheus_client import Counter, Histogram
from django.conf import settings
from opentelemetry.trace import SpanKind, Status, StatusCode
from .telemetry import span, identifiers

REQUESTS = Counter("http_requests_total", "Completed HTTP requests", ["route", "method", "status"])
LATENCY = Histogram(
    "http_request_seconds",
    "HTTP latency",
    ["route", "method"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
EVENTS = Counter("event_processing_total", "Event outcomes", ["outcome"])
LOCK_TIME = Histogram("portfolio_lock_wait_seconds", "Time waiting for a portfolio lock")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        value = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": settings.SERVICE,
            "message": record.getMessage(),
        }
        for key in (
            "request_id",
            "event_id",
            "service",
            "outcome",
            "duration_ms",
            "error_code",
            "process_id",
            "process_kind",
            "process_state",
            "route",
            "method",
            "status",
        ):
            if hasattr(record, key):
                value[key] = getattr(record, key)
        value.update(identifiers())
        if record.exc_info:
            value["exception"] = record.exc_info[0].__name__
        return json.dumps(value)


class RequestMetrics:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in ("/metrics", "/health/live", "/health/ready"):
            return self.handle(request)
        with span(
            "http.request",
            kind=SpanKind.SERVER,
            parent={
                key.lower(): value
                for key, value in request.headers.items()
                if key.lower() in ("traceparent", "tracestate")
            },
        ) as current:
            response = self.handle(request)
            match = getattr(request, "resolver_match", None)
            current.update_name(f"{request.method} {match.route if match else 'unmatched'}")
            current.set_attribute("http.request.method", request.method)
            current.set_attribute("http.response.status_code", response.status_code)
            if response.status_code >= 500:
                current.set_status(Status(StatusCode.ERROR))
            ids = identifiers()
            if ids:
                response["X-Trace-ID"] = ids["trace_id"]
            return response

    def handle(self, request):
        request.request_id = str(uuid.uuid4())
        start = time.monotonic()
        response = self.get_response(request)
        match = getattr(request, "resolver_match", None)
        route = match.route if match else "unmatched"
        if route not in ("metrics", "health/live", "health/ready"):
            REQUESTS.labels(route, request.method, str(response.status_code)).inc()
            LATENCY.labels(route, request.method).observe(time.monotonic() - start)
        if route not in ("metrics", "health/live", "health/ready"):
            logging.getLogger(__name__).info(
                "http_completed",
                extra={
                    "request_id": request.request_id,
                    "route": route,
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - start) * 1000),
                },
            )
        response["X-Request-ID"] = request.request_id
        if response.status_code >= 500:
            logging.getLogger(__name__).error(
                "request_failed",
                extra={
                    "request_id": request.request_id,
                    "duration_ms": round((time.monotonic() - start) * 1000),
                },
            )
        return response
