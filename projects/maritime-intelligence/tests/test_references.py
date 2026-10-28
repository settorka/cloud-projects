import json
from datetime import UTC, datetime, timedelta

from v1.adapters.references import minimize
from v1.services import store_reference


class MemoryStore:
    def __init__(self):
        self.objects = {}

    def put(self, key, body):
        self.objects[key] = body


def test_retry_is_stable_and_snapshot_preserves_provenance():
    store = MemoryStore()
    at = datetime(2026, 10, 28, 10, tzinfo=UTC)
    payload = {"portCalls": [{"portCallId": 1}]}
    key = store_reference(store, payload, 900, at)
    assert store_reference(store, payload, 900, at + timedelta(minutes=1)) == key
    assert len(store.objects) == 1
    assert json.loads(store.objects[key])["attribution"]["license"] == "CC BY 4.0"
    assert store_reference(store, payload, 900, at + timedelta(minutes=15)) != key


def test_unneeded_personal_and_free_text_fields_are_removed():
    payload = {
        "portCalls": [
            {
                "portCallId": 1,
                "mmsi": 230123456,
                "shipMasterArrival": "unneeded name",
                "agentInfo": {"email": "x"},
                "freeTextArrival": "unbounded text",
                "portAreaDetails": [{"portAreaCode": "A", "contact": "x"}],
            }
        ]
    }
    result = minimize(payload)["portCalls"][0]
    assert "shipMasterArrival" not in result and "agentInfo" not in result
    assert result["portAreaDetails"] == [{"portAreaCode": "A"}]
