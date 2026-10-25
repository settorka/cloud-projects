"""Bounded official-data ingestion. Aggregate inputs never become private forecasts."""

import asyncio
import hashlib
import json
from datetime import timedelta
import httpx
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .models import SourceRecord, ImportRun, JobStatus

BASE = "https://data.elexon.co.uk/bmrs/api/v1"
ENDPOINTS = {
    "wind": "forecast/generation/wind/latest",
    "generation": "generation/actual/per-type/wind-and-solar",
    "prices": "balancing/pricing/market-index",
}


async def fetch_dataset(client, name, start, end, semaphore):
    async with semaphore:
        for attempt in range(3):
            try:
                async with client.stream(
                    "GET",
                    f"{BASE}/{ENDPOINTS[name]}",
                    params={"from": start.isoformat(), "to": end.isoformat(), "format": "json"},
                ) as response:
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt == 2:
                            response.raise_for_status()
                        await asyncio.sleep(min(4, 2**attempt))
                        continue
                    response.raise_for_status()
                    content = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        content.extend(chunk)
                        if len(content) > 10 * 1024 * 1024:
                            raise ValueError("Response exceeds 10 MiB ingestion bound")
                    body = json.loads(content)
                records = body.get("data") if isinstance(body, dict) else body
                if not isinstance(records, list) or not records or len(records) > 10000:
                    raise ValueError("Empty/invalid/oversized data array")
                for row in records:
                    if not isinstance(row, dict) or not parse_datetime(row.get("startTime", "")):
                        raise ValueError("Missing startTime")
                return records
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 2:
                    raise
                await asyncio.sleep(2**attempt)
    raise RuntimeError("Retry budget exhausted")


async def fetch_all(names, start, end, transport=None):
    if end <= start or end - start > timedelta(days=1):
        raise ValueError("Import window must be positive and at most 24 hours")
    semaphore = asyncio.Semaphore(2)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20, connect=5),
        limits=httpx.Limits(max_connections=2),
        transport=transport,
        follow_redirects=False,
    ) as client:
        async with asyncio.TaskGroup() as group:
            tasks = {
                name: group.create_task(fetch_dataset(client, name, start, end, semaphore))
                for name in names
            }
        return {name: task.result() for name, task in tasks.items()}


def persist(records):
    # Store source content and its publication timestamp; never relabel it as an asset forecast.
    with transaction.atomic():
        count = 0
        for dataset, rows in records.items():
            for row in rows:
                raw = json.dumps(row, sort_keys=True, separators=(",", ":"))
                identity = hashlib.sha256(f"{dataset}:{raw}".encode()).hexdigest()
                start = parse_datetime(row["startTime"])
                published = parse_datetime(row.get("publishTime", ""))
                if not start or not start.tzinfo or (published and not published.tzinfo):
                    raise ValueError("Source timestamps must be timezone-aware")
                _, created = SourceRecord.objects.get_or_create(
                    identity=identity,
                    defaults={
                        "dataset": dataset,
                        "start": start,
                        "published_at": published,
                        "payload": row,
                    },
                )
                count += int(created)
        return count


def import_live(names, start, end):
    run = ImportRun.objects.create(source="elexon", state="RUNNING")
    try:
        count = persist(asyncio.run(fetch_all(names, start, end)))
    except Exception as exc:
        run.state = "FAILED"
        run.error = type(exc).__name__
        run.completed_at = timezone.now()
        run.save()
        JobStatus.objects.update_or_create(
            name="elexon_import", defaults={"last_error": type(exc).__name__}
        )
        raise
    run.state = "SUCCEEDED"
    run.records = count
    run.completed_at = timezone.now()
    run.save()
    JobStatus.objects.update_or_create(
        name="elexon_import", defaults={"last_success": timezone.now(), "last_error": ""}
    )
    return run
