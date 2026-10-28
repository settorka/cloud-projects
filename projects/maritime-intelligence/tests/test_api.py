from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from v1.api import create_app


class Repository:
    def latest(self, mmsi):
        return {"mmsi": mmsi, "event_time": datetime.now(UTC) - timedelta(hours=2)}

    def history(self, *args):
        return []


def test_authentication_and_stale_data_are_explicit(settings):
    headers = {"Authorization": f"Bearer {settings.api_token}"}
    client = TestClient(create_app(Repository(), settings))
    assert client.get("/health/live").status_code == 200
    assert client.get("/v1/vessels/230123456/latest").status_code == 401
    response = client.get("/v1/vessels/230123456/latest", headers=headers)
    assert response.status_code == 200 and response.json()["freshness"] == "expired"


def test_history_range_and_cursor_validation(settings):
    headers = {"Authorization": f"Bearer {settings.api_token}"}
    client = TestClient(create_app(Repository(), settings))
    now = datetime.now(UTC)
    params = {"start": (now - timedelta(hours=25)).isoformat(), "end": now.isoformat()}
    assert (
        client.get("/v1/vessels/230123456/positions", params=params, headers=headers).status_code
        == 400
    )
    params["start"] = (now - timedelta(hours=1)).isoformat()
    params["cursor"] = "invalid!"
    assert (
        client.get("/v1/vessels/230123456/positions", params=params, headers=headers).status_code
        == 400
    )
