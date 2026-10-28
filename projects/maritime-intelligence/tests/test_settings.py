from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from v1.api import create_app
from v1.settings import Settings
from v1.visits import VisitRules, VisitState, advance


def test_required_value_has_no_hidden_fallback(settings, monkeypatch):
    monkeypatch.delenv("KAFKA_TOPIC")
    with pytest.raises(ValueError, match="KAFKA_TOPIC"):
        Settings.load()


@pytest.mark.parametrize(
    "key,value",
    [
        ("S3_PATH_STYLE", "maybe"),
        ("KAFKA_POLL_SECONDS", "0"),
        ("AIS_BBOX", "nan,59,30,66"),
        ("API_PORT", "65536"),
        ("API_PAGE_SIZE", "1001"),
        ("REFERENCE_API_URL", "http://insecure.example"),
    ],
)
def test_invalid_configuration_fails_before_services_start(settings, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        Settings.load()


def test_environment_overrides_dotenv(settings, monkeypatch, tmp_path):
    path = tmp_path / ".env"
    path.write_text("KAFKA_TOPIC=from-file\n")
    monkeypatch.setenv("ENV_FILE", str(path))
    monkeypatch.setenv("KAFKA_TOPIC", "from-exported-environment")
    assert Settings.load().kafka_topic == "from-exported-environment"


def test_custom_api_limits_and_freshness_are_used(settings):
    class Repository:
        def latest(self, mmsi):
            return {"event_time": datetime.now(UTC) - timedelta(minutes=6)}

    configured = replace(
        settings, fresh_seconds=600, expired_seconds=1200, api_page_size=1, api_max_page_size=2
    )
    client = TestClient(create_app(Repository(), configured))
    headers = {"Authorization": f"Bearer {configured.api_token}"}
    assert (
        client.get("/v1/vessels/230123456/latest", headers=headers).json()["freshness"] == "fresh"
    )
    now = datetime.now(UTC)
    response = client.get(
        "/v1/vessels/230123456/positions",
        headers=headers,
        params={
            "start": (now - timedelta(hours=1)).isoformat(),
            "end": now.isoformat(),
            "limit": 3,
        },
    )
    assert response.status_code == 422


def test_visit_thresholds_are_injected_instead_of_global_constants():
    rules = VisitRules(
        arrival_observations=2,
        arrival_seconds=60,
        departure_observations=2,
        departure_seconds=30,
        gap_seconds=120,
    )
    at = datetime.now(UTC)
    state, event = advance(VisitState(), at, True, False, rules)
    assert event is None
    state, event = advance(state, at + timedelta(seconds=60), True, False, rules)
    assert state.phase == "inside" and event == "arrival"
