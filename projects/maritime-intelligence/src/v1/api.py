import base64
import json
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from opentelemetry import metrics, trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from v1.models import freshness
from v1.services import ATTRIBUTION
from v1.telemetry import operation


def create_app(repository, settings, telemetry=None):
    app = FastAPI(title="Maritime intelligence", version="0.1.0")
    tracer = telemetry.traces.get_tracer("maritime") if telemetry else trace.get_tracer("maritime")
    meter = telemetry.meter.get_meter("maritime") if telemetry else metrics.get_meter("maritime")
    requests = meter.create_counter("maritime.http.requests")
    errors = meter.create_counter("maritime.http.errors")
    duration = meter.create_histogram("maritime.http.duration", unit="s")

    @app.middleware("http")
    async def observe(request, call_next):
        if request.url.path == "/health/live":
            return await call_next(request)
        method = (
            request.method
            if request.method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
            else "OTHER"
        )
        parent = TraceContextTextMapPropagator().extract(request.headers)
        with operation(
            "HTTP request",
            tracer=tracer,
            context=parent,
            kind=trace.SpanKind.SERVER,
            record_exception=False,
        ) as span:
            started = time.perf_counter()
            status = 500
            try:
                response = await call_next(request)
                status = response.status_code
                return response
            finally:
                route = getattr(request.scope.get("route"), "path", "unmatched")
                span.update_name(method + " " + route)
                span.set_attributes(
                    {
                        "http.request.method": method,
                        "http.route": route,
                        "http.response.status_code": status,
                    }
                )
                if status >= 500:
                    errors.add(1)
                    span.set_status(trace.Status(trace.StatusCode.ERROR))
                requests.add(1)
                duration.record(time.perf_counter() - started)
                logging.getLogger("maritime.api").info("%s %s status=%s", method, route, status)

    bearer = HTTPBearer(auto_error=False)

    def authenticate(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if credentials is None or not secrets.compare_digest(
            credentials.credentials, settings.api_token
        ):
            raise HTTPException(
                401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"}
            )

    protected = [Depends(authenticate)]

    @app.exception_handler(psycopg.Error)
    async def database_error(request, exc):
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/v1/status", dependencies=protected)
    def status():
        data = repository.status()
        event = data.get("last_event_time")
        return {
            **data,
            "data_freshness": freshness(
                event, datetime.now(UTC), settings.fresh_seconds, settings.expired_seconds
            )
            if event
            else "unknown",
            "coverage": "Configured source and bounding box only; completeness unverified",
            "attribution": ATTRIBUTION,
        }

    @app.get("/v1/vessels/{mmsi}/latest", dependencies=protected)
    def latest(mmsi: str):
        check_mmsi(mmsi)
        row = repository.latest(mmsi)
        if row is None:
            raise HTTPException(404, "No observation; absence does not establish vessel inactivity")
        return {
            **row,
            "freshness": freshness(
                row["event_time"],
                datetime.now(UTC),
                settings.fresh_seconds,
                settings.expired_seconds,
            ),
            "attribution": ATTRIBUTION,
        }

    @app.get("/v1/vessels/{mmsi}/positions", dependencies=protected)
    def positions(
        mmsi: str,
        start: datetime,
        end: datetime,
        limit: Annotated[int, Query(ge=1, le=settings.api_max_page_size)] = settings.api_page_size,
        cursor: str | None = None,
    ):
        check_mmsi(mmsi)
        if start.utcoffset() is None or end.utcoffset() is None:
            raise HTTPException(400, "Timezone-aware start and end required")
        if not timedelta(0) < end - start <= timedelta(hours=settings.api_history_hours):
            raise HTTPException(
                400, f"Time range must be positive and at most {settings.api_history_hours} hours"
            )
        if start < datetime.now(UTC) - timedelta(days=settings.position_retention_days):
            raise HTTPException(
                400, f"Detailed position retention is {settings.position_retention_days} days"
            )
        after = None
        if cursor:
            try:
                stamp, identity = json.loads(base64.urlsafe_b64decode(cursor))
                at = datetime.fromisoformat(stamp)
                if at.utcoffset() is None or not isinstance(identity, str):
                    raise ValueError()
                after = (at, identity)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise HTTPException(400, "Invalid cursor") from exc
        rows = repository.history(mmsi, start, end, limit + 1, after)
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_cursor = base64.urlsafe_b64encode(
                json.dumps([rows[-1]["event_time"].isoformat(), rows[-1]["event_id"]]).encode()
            ).decode()
        return {"items": rows, "next_cursor": next_cursor, "attribution": ATTRIBUTION}

    @app.get("/v1/ports/{port_id}/visits", dependencies=protected)
    def visits(
        port_id: str,
        limit: Annotated[int, Query(ge=1, le=settings.api_max_page_size)] = settings.api_page_size,
    ):
        return {
            "items": repository.visits(port_id, limit),
            "classification": "inferred",
            "attribution": ATTRIBUTION,
        }

    return app


def check_mmsi(mmsi):
    import re

    if not re.fullmatch(r"[0-9]{9}", mmsi):
        raise HTTPException(400, "MMSI must contain nine ASCII digits")
