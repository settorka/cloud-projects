"""Source-independent observation contract; no infrastructure imports."""

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True)
class Observation:
    source: str
    mmsi: str
    event_time: datetime
    received_at: datetime
    lon: float
    lat: float
    sog: float | None = None
    cog: float | None = None

    def __post_init__(self):
        if not re.fullmatch(r"[0-9]{9}", self.mmsi):
            raise ValueError("MMSI must contain nine ASCII digits")
        if not self.source or len(self.source) > 64:
            raise ValueError("source must contain 1–64 characters")
        for name in ("event_time", "received_at"):
            if getattr(self, name).utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if not math.isfinite(self.lon) or not -180 <= self.lon <= 180:
            raise ValueError("invalid longitude")
        if not math.isfinite(self.lat) or not -90 <= self.lat <= 90:
            raise ValueError("invalid latitude")
        if self.event_time < datetime(2000, 1, 1, tzinfo=UTC):
            raise ValueError("event predates supported AIS history")
        if self.event_time > self.received_at + timedelta(minutes=5):
            raise ValueError("event time exceeds receipt time by more than five minutes")
        if self.sog is not None and (not math.isfinite(self.sog) or not 0 <= self.sog < 102.3):
            raise ValueError("invalid speed; unavailable sentinel must be null")
        if self.cog is not None and (not math.isfinite(self.cog) or not 0 <= self.cog < 360):
            raise ValueError("invalid course; unavailable sentinel must be null")

    def to_dict(self):
        return {
            **asdict(self),
            "event_time": self.event_time.astimezone(UTC).isoformat(),
            "received_at": self.received_at.astimezone(UTC).isoformat(),
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            **{
                **data,
                "event_time": datetime.fromisoformat(data["event_time"]),
                "received_at": datetime.fromisoformat(data["received_at"]),
            }
        )

    @property
    def event_id(self):
        # Retransmission time is not part of observation identity. Source is retained to
        # avoid silently conflating independent provider evidence.
        value = self.to_dict()
        value.pop("received_at")
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def freshness(event_time: datetime, now: datetime, fresh_seconds: int, expired_seconds: int) -> str:
    age = (now - event_time).total_seconds()
    if age < -300:
        return "unknown"
    if age <= fresh_seconds:
        return "fresh"
    return "stale" if age <= expired_seconds else "expired"
