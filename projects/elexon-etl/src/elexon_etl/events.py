"""Small JSON events consumed by both a terminal and Azure Monitor."""

import json
from datetime import datetime, timezone


def emit(event, **fields):
    print(
        json.dumps(
            {
                "application": "elexon-etl",
                "event": event,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **fields,
            },
            sort_keys=True,
        ),
        flush=True,
    )
