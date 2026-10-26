import asyncio
from datetime import timedelta
from decimal import Decimal
import httpx
import pytest
from django.utils import timezone
from app.domain import write_value, scenario_start
from app.models import MarketValue, MarketRevision, Outbox, SourceRecord
from app.elexon import fetch_all, persist


@pytest.mark.django_db
def test_versions_dedup_and_atomic_outbox(event_guard):
    now = timezone.now()
    start = scenario_start()
    write_value("forecast", "demo", start, 100, now, now + timedelta(days=2))
    write_value("forecast", "demo", start, 100, now, now + timedelta(days=2))
    assert MarketRevision.objects.count() == 1 and Outbox.objects.count() == 1
    write_value("forecast", "demo", start, 60, now + timedelta(seconds=1), now + timedelta(days=2))
    write_value("forecast", "demo", start, 90, now - timedelta(seconds=1), now + timedelta(days=2))
    assert MarketValue.objects.get().quantity == Decimal(60)
    assert MarketRevision.objects.count() == 2


@pytest.mark.django_db
def test_negative_generation_invalid_negative_price_valid(event_guard):
    now = timezone.now()
    start = scenario_start()
    with pytest.raises(ValueError):
        write_value("forecast", "demo", start, -1, now, now + timedelta(days=1))
    write_value("price", "", start, -20, now, now + timedelta(days=1))
    assert MarketValue.objects.get().quantity == -20


@pytest.mark.asyncio
async def test_fetch_is_bounded_concurrent():
    active = 0
    peak = 0

    async def respond(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(
            200, json={"data": [{"startTime": "2026-10-25T00:00:00Z", "generation": 100}]}
        )

    end = timezone.now()
    result = await fetch_all(
        ["wind", "generation", "prices"],
        end - timedelta(hours=1),
        end,
        httpx.MockTransport(respond),
    )
    assert set(result) == {"wind", "generation", "prices"}
    assert peak == 2


@pytest.mark.asyncio
async def test_bad_payload_fails():
    end = timezone.now()
    with pytest.raises(ExceptionGroup):
        await fetch_all(
            ["wind"],
            end - timedelta(hours=1),
            end,
            httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []})),
        )


@pytest.mark.django_db
def test_real_aggregate_is_not_private_forecast():
    row = {
        "startTime": "2026-10-25T00:00:00Z",
        "publishTime": "2026-10-24T12:00:00Z",
        "generation": 20000,
    }
    assert persist({"wind": [row]}) == 1
    assert persist({"wind": [row]}) == 0
    assert SourceRecord.objects.count() == 1
    assert not MarketValue.objects.exists() and not Outbox.objects.exists()


@pytest.mark.django_db
def test_source_records_api(client):
    persist({"wind": [{"startTime": "2026-10-25T00:00:00Z", "generation": 20000}]})
    response = client.get("/v1/source-records?dataset=wind&limit=1000")
    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["results"][0]["payload"]["generation"] == 20000
    assert client.get("/v1/source-records?dataset=unknown").status_code == 400


@pytest.mark.django_db
def test_import_state_history_success(monkeypatch):
    from app.elexon import import_live
    from app.models import ProcessExecution

    async def fetched(*args):
        return {"wind": [{"startTime": "2026-10-25T00:00:00Z", "generation": 100}]}

    monkeypatch.setattr("app.elexon.fetch_all", fetched)
    end = timezone.now()
    run = import_live(["wind"], end - timedelta(hours=1), end)
    process = ProcessExecution.objects.get(identity=str(run.pk))
    assert run.state == "SUCCEEDED" and run.records == 1
    assert list(process.transitions.order_by("sequence").values_list("state", flat=True)) == [
        "CREATED",
        "FETCHING",
        "FETCHED",
        "PERSISTING",
        "SUCCEEDED",
    ]


@pytest.mark.django_db
def test_import_state_history_failure(monkeypatch):
    from app.elexon import import_live
    from app.models import ProcessExecution, ImportRun

    async def failed(*args):
        raise TimeoutError("private-source-details")

    monkeypatch.setattr("app.elexon.fetch_all", failed)
    end = timezone.now()
    with pytest.raises(TimeoutError):
        import_live(["wind"], end - timedelta(hours=1), end)
    assert ImportRun.objects.get().state == "FAILED"
    process = ProcessExecution.objects.get()
    assert process.state == "FAILED" and process.error_code == "TimeoutError"
    assert not SourceRecord.objects.exists()
