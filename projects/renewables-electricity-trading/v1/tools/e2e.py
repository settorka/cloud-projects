"""Compose acceptance test, including actual broker redelivery and schema isolation."""

import argparse
import json
import os
import subprocess
import time
import uuid

import httpx

ENV_FILE = ".env.example"
TOKEN = os.getenv("TRADER_TOKEN", "1" * 40)
HEADERS = {"Authorization": f"Token {TOKEN}"}


def compose(*args):
    return subprocess.check_output(
        ["docker", "compose", "--env-file", ENV_FILE, *args], text=True
    ).strip()


def wait_for(fn, description, timeout=40):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        try:
            result = fn()
            if result:
                return result
        except (httpx.HTTPError, AssertionError, KeyError) as exc:
            last = str(exc)
        time.sleep(0.25)
    raise AssertionError(f"Timed out: {description}; last={last}")


def main():
    global ENV_FILE, HEADERS
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env.example")
    options = parser.parse_args()
    ENV_FILE = options.env_file
    from pathlib import Path

    values = {}
    for line in Path(ENV_FILE).read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip().strip("\"'")
    HEADERS = {"Authorization": "Token " + os.getenv("TRADER_TOKEN", values["TRADER_TOKEN"])}
    # Isolated new portfolio prevents previous manual data from changing assertions.
    portfolio = "e2e-" + uuid.uuid4().hex[:8]
    code = f"from app.models import *; from django.contrib.auth.models import User; p=Portfolio.objects.create(id='{portfolio}',name='E2E',lower_limit=0,upper_limit=200); Membership.objects.create(user=User.objects.get(username='trader'),portfolio=p,role='trader')"
    compose("exec", "-T", "trading", "python", "manage.py", "shell", "-c", code)
    compose(
        "exec",
        "-T",
        "valuation",
        "python",
        "manage.py",
        "shell",
        "-c",
        f"from app.models import PortfolioAccess; from django.contrib.auth.models import User; PortfolioAccess.objects.create(user=User.objects.get(username='trader'),portfolio='{portfolio}')",
    )
    start = compose(
        "exec",
        "-T",
        "market-data",
        "python",
        "manage.py",
        "scenario",
        "--portfolio",
        portfolio,
    ).splitlines()[-1]
    with httpx.Client(headers=HEADERS, timeout=15) as c:

        def positions():
            return c.get(f"http://127.0.0.1:8001/v1/portfolios/{portfolio}/positions").json()[
                "results"
            ]

        wait_for(lambda: len(positions()) == 4, "forecast delivery")
        body = {
            "portfolio": portfolio,
            "counterparty": "grid-buyer",
            "direction": "SELL",
            "reason": "E2E sale",
            "legs": [{"start": start, "quantity": "80.000", "price": "70.0000"}],
        }
        key = str(uuid.uuid4())
        response = c.post(
            "http://127.0.0.1:8001/v1/trades",
            json=body,
            headers={"Idempotency-Key": key},
        )
        assert response.status_code == 201, response.text
        trade_id = response.json()["trade"]["id"]
        assert (
            c.post(
                "http://127.0.0.1:8001/v1/trades",
                json=body,
                headers={"Idempotency-Key": key},
            ).headers["Idempotent-Replay"]
            == "true"
        )
        wait_for(
            lambda: any(str(x["sales"]) in ["80.000", "80.0", "80"] for x in positions()),
            "sale projection",
        )

        def valuation():
            r = c.post("http://127.0.0.1:8003/v1/valuation-runs", json={"portfolio": portfolio})
            assert r.status_code == 201, r.text
            return r.json()

        wait_for(
            lambda: valuation()["input_versions"]["trades"].get(trade_id) == 1,
            "trade delivery to valuation",
        )
        duplicate_code = (
            "import json; from app.models import Outbox; from app.events import sqs,queue_url; "
            f"row=Outbox.objects.filter(envelope__entity_id='{trade_id}').first(); "
            "client=sqs(); url=queue_url(client,'valuation-input'); "
            "client.send_message(QueueUrl=url,MessageBody=json.dumps(row.envelope)); "
            "client.send_message(QueueUrl=url,MessageBody=json.dumps(row.envelope))"
        )
        compose("exec", "-T", "trading", "python", "manage.py", "shell", "-c", duplicate_code)
        result = valuation()
        assert float(result["total"]) == -800, result
        # Stop consumer, publish, then restore it: queue must preserve work.
        compose("stop", "trading-worker")
        try:
            compose(
                "exec",
                "-T",
                "market-data",
                "python",
                "manage.py",
                "scenario",
                "--portfolio",
                portfolio,
                "--forecast",
                "60",
                "--start",
                start,
            )
            wait_for(
                lambda: positions()[0]["forecast"] in [100, "100.000"],
                "unchanged while worker stopped",
            )
        finally:
            compose("start", "trading-worker")
        wait_for(
            lambda: any(float(x["expected_exposure"]) == -20 and x["breach"] for x in positions()),
            "forecast breach",
        )
        cover = {
            **body,
            "direction": "BUY",
            "legs": [{**body["legs"][0], "quantity": "20.000"}],
        }
        r = c.post(
            "http://127.0.0.1:8001/v1/trades",
            json=cover,
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert r.status_code == 201, r.text
        assert float(positions()[0]["expected_exposure"]) == 0
        compose("exec", "-T", "trading", "python", "manage.py", "reconcile", portfolio)
        assert c.get("http://127.0.0.1:8001/v1/portfolios/restricted/positions").status_code == 403
        for service in ["trading", "market-data", "valuation"]:
            target = "valuation" if service == "trading" else "trading"
            code = f"from django.db import connection; connection.cursor().execute('SELECT * FROM {target}.django_migrations LIMIT 1')"
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "--env-file",
                    ENV_FILE,
                    "exec",
                    "-T",
                    service,
                    "python",
                    "manage.py",
                    "shell",
                    "-c",
                    code,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            assert result.returncode != 0 and "permission denied" in result.stderr, result.stderr
    print(
        json.dumps(
            {
                "status": "passed",
                "portfolio": portfolio,
                "checks": [
                    "booking",
                    "retry",
                    "position",
                    "valuation",
                    "worker recovery",
                    "forecast breach",
                    "cover",
                    "reconciliation",
                    "authorization",
                    "schema isolation",
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
