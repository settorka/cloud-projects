"""Bounded HTTPS fetch, usable in a CLI or Lambda without extra HTTP dependencies."""

import gzip
import io
import json
from urllib.request import Request, urlopen

CALL_FIELDS = {
    "portCallId",
    "portCallTimestamp",
    "portToVisit",
    "prevPort",
    "nextPort",
    "vesselName",
    "imoLloyds",
    "mmsi",
    "vesselTypeCode",
}
AREA_FIELDS = {"portAreaCode", "eta", "ata", "etd", "atd", "berthCode"}


def minimize(payload):
    """Do not persist agent/master names, contact details or arbitrary free text."""
    calls = []
    for item in payload["portCalls"]:
        if not isinstance(item, dict) or "portCallId" not in item:
            raise ValueError("port call lacks identity")
        safe = {key: value for key, value in item.items() if key in CALL_FIELDS}
        safe["portAreaDetails"] = [
            {key: value for key, value in area.items() if key in AREA_FIELDS}
            for area in (item.get("portAreaDetails") or [])
        ]
        calls.append(safe)
    return {"dataUpdatedTime": payload.get("dataUpdatedTime"), "portCalls": calls}


def fetch_port_calls(settings):
    request = Request(
        settings.reference_url,
        headers={"Accept-Encoding": "gzip", "Digitraffic-User": settings.source_user_agent},
    )
    with urlopen(request, timeout=settings.http_timeout_seconds) as response:
        body = response.read(settings.reference_max_bytes + 1)
        if len(body) > settings.reference_max_bytes:
            raise ValueError("reference response exceeds limit")
        if response.headers.get("Content-Encoding") == "gzip":
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
                body = stream.read(settings.reference_max_bytes + 1)
    if len(body) > settings.reference_max_bytes:
        raise ValueError("decompressed reference exceeds limit")
    payload = json.loads(body)
    if not isinstance(payload, dict) or not isinstance(payload.get("portCalls"), list):
        raise ValueError("unexpected port-call schema")
    return minimize(payload)
