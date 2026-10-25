"""Open-loop bounded load generator. Run with a service uv environment or Compose tools profile."""

import argparse
import asyncio
import json
import math
import os
import random
import time
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx


def tomorrow():
    day = datetime.now(ZoneInfo("Europe/London")).date() + timedelta(days=1)
    return datetime(day.year, day.month, day.day, 13, tzinfo=UTC).isoformat()


def write_result(path, result):
    with open(path, "w") as f:
        json.dump(result, f, indent=2)


async def run(args):
    if (
        not 0 < args.rate <= 10000
        or not 1 <= args.concurrency <= 1000
        or not 1 <= args.requests <= 100000
    ):
        raise ValueError("Invalid bounded load parameters")
    token = os.environ["TRADER_TOKEN"]
    rng = random.Random(args.seed)
    outcomes = Counter()
    latencies = []
    lag = []
    shed = 0
    pending = set()
    requests = []
    records = []
    async with httpx.AsyncClient(
        base_url=args.url,
        headers={"Authorization": f"Token {token}"},
        timeout=10,
        limits=httpx.Limits(
            max_connections=args.concurrency, max_keepalive_connections=args.concurrency
        ),
    ) as client:

        async def send(index, body, key):
            begin = time.monotonic()
            record = {"index": index, "key": key, "body": body}
            try:
                response = await client.post(
                    "/v1/trades", json=body, headers={"Idempotency-Key": key}
                )
                record["http_status"] = response.status_code
                record["idempotent_replay"] = response.headers.get("Idempotent-Replay") == "true"
                outcomes[str(response.status_code)] += 1
                if response.headers.get("Idempotent-Replay") == "true":
                    outcomes["idempotent_replay"] += 1
            except httpx.HTTPError as exc:
                record["error"] = type(exc).__name__
                outcomes[type(exc).__name__] += 1
            finally:
                duration = time.monotonic() - begin
                latencies.append(duration)
                record["duration_seconds"] = duration
                records.append(record)

        started = time.monotonic()
        prefix = str(uuid.uuid4())
        for i in range(args.requests):
            due = started + i / args.rate
            await asyncio.sleep(max(0, due - time.monotonic()))
            lag.append(max(0, time.monotonic() - due))
            if args.duplicates and i and i % 10 == 0:
                body, key = requests[-1]
            else:
                body = {
                    "portfolio": args.portfolio,
                    "counterparty": "grid-buyer",
                    "direction": rng.choice(["BUY", "SELL"]),
                    "reason": "seeded load test",
                    "legs": [{"start": args.start, "quantity": "0.001", "price": "70.0000"}],
                }
                key = f"{prefix}-{i}"
            requests.append((body, key))
            if len(pending) >= args.concurrency:
                shed += 1
                continue
            task = asyncio.create_task(send(i, body, key))
            pending.add(task)
            task.add_done_callback(pending.discard)
        if pending:
            await asyncio.gather(*pending)
        elapsed = time.monotonic() - started

    def percentile(values, p):
        return (
            sorted(values)[min(len(values) - 1, math.ceil(len(values) * p) - 1)] if values else None
        )

    result = {
        "run_id": prefix,
        "seed": args.seed,
        "intended_requests": args.requests,
        "target_rate": args.rate,
        "sent_requests": len(latencies),
        "generator_shed": shed,
        "elapsed_seconds": elapsed,
        "completed_requests_per_second": len(latencies) / elapsed,
        "outcomes": dict(outcomes),
        "latency_seconds": {
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
        },
        "max_generator_schedule_lag_seconds": max(lag, default=0),
        "note": "201 counts include idempotent replays; distinguish them. Verify final positions with reconcile.",
    }
    print(json.dumps(result, indent=2))
    if args.output:
        await asyncio.to_thread(write_result, args.output, {**result, "requests": records})
    if shed or any(k not in ["200", "201", "422", "idempotent_replay"] for k in outcomes):
        return 1
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8001")
    p.add_argument("--requests", type=int, default=100)
    p.add_argument("--rate", type=float, default=10)
    p.add_argument("--concurrency", type=int, default=20)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--portfolio", default="demo")
    p.add_argument("--start", default=tomorrow())
    p.add_argument("--duplicates", action="store_true")
    p.add_argument("--output")
    raise SystemExit(asyncio.run(run(p.parse_args())))


if __name__ == "__main__":
    main()
