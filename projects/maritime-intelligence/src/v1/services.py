import hashlib
import json
from datetime import UTC, datetime

ATTRIBUTION = {
    "provider": "Fintraffic Digitraffic",
    "license": "CC BY 4.0",
    "url": "https://www.digitraffic.fi/en/marine-traffic/",
}


def store_reference(
    store, payload: dict, interval_seconds: int, now: datetime | None = None
) -> str:
    """Content-addressed snapshots make unchanged scheduled retries harmless."""
    captured = (now or datetime.now(UTC)).astimezone(UTC)
    # An unchanged retry within the same scheduled interval uses the same immutable key.
    captured = datetime.fromtimestamp(
        int(captured.timestamp()) // interval_seconds * interval_seconds, UTC
    )
    body = json.dumps(
        {"data": payload, "attribution": ATTRIBUTION, "captured_at": captured.isoformat()},
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(body).hexdigest()
    prefix = captured.strftime("references/%Y/%m/%d/%H%M%S")
    key = f"{prefix}-{digest}.json"
    store.put(key, body)
    return key
