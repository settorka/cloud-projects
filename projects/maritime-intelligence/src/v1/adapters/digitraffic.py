import json
from datetime import UTC, datetime

from v1.models import Observation


def normalize(topic: str, payload: bytes, received_at: datetime) -> tuple[Observation, dict]:
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != "vessels-v2" or parts[2] != "location":
        raise ValueError("unsupported MQTT topic")
    raw = json.loads(payload)
    if not isinstance(raw, dict):
        raise ValueError("location must be a JSON object")
    # Location time is epoch seconds; metadata uses milliseconds. Do not guess units.
    stamp = raw["time"]
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
        raise ValueError("time must be epoch seconds")
    at = datetime.fromtimestamp(stamp, UTC)
    sog, cog = raw.get("sog"), raw.get("cog")
    observation = Observation(
        "digitraffic",
        parts[1],
        at,
        received_at,
        float(raw["lon"]),
        float(raw["lat"]),
        None if sog is None or sog == 102.3 else float(sog),
        None if cog is None or cog == 360 else float(cog),
    )
    return observation, raw
