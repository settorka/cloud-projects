"""Restore a local dump into a unique rehearsal database, verify, and clean it up."""

import argparse
import os
from environment import load_environment
import json
import re
import subprocess
import time
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args()
    env_file = str(load_environment(args.env_file))
    database = os.environ["DB_NAME"]
    base = ["docker", "compose", "--env-file", env_file]
    target = "restore_" + uuid.uuid4().hex[:12]

    def command(*argv, input=None):
        return subprocess.run([*base, *argv], input=input, capture_output=True, check=True).stdout

    schemas = [
        os.environ[key]
        for key in ("TRADING_DB_SCHEMA", "MARKET_DATA_DB_SCHEMA", "VALUATION_DB_SCHEMA")
    ]
    if not all(re.fullmatch(r"[a-z_][a-z0-9_]*", name) for name in schemas):
        raise ValueError("Invalid schema identifier")
    trading, market, valuation = schemas
    query = (
        f"SELECT (SELECT count(*) FROM {trading}.app_trade), "
        f"(SELECT count(*) FROM {trading}.app_traderevision), "
        f"(SELECT count(*) FROM {market}.app_marketrevision), "
        f"(SELECT count(*) FROM {valuation}.app_valuationrun)"
    )

    start = time.monotonic()
    created = False
    try:
        # Caller must quiesce writers for a meaningful cross-check.
        dump = command("exec", "-T", "postgres", "pg_dump", "-U", "postgres", "-d", database, "-Fc")
        before = command(
            "exec", "-T", "postgres", "psql", "-U", "postgres", "-d", database, "-Atc", query
        )
        command("exec", "-T", "postgres", "createdb", "-U", "postgres", target)
        created = True
        command(
            "exec",
            "-T",
            "postgres",
            "pg_restore",
            "-U",
            "postgres",
            "-d",
            target,
            "--exit-on-error",
            input=dump,
        )
        after = command(
            "exec", "-T", "postgres", "psql", "-U", "postgres", "-d", target, "-Atc", query
        )
        assert before == after, (before, after)
        portfolios = (
            command(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "postgres",
                "-d",
                target,
                "-Atc",
                "SELECT id FROM trading.app_portfolio ORDER BY id",
            )
            .decode()
            .splitlines()
        )
        for portfolio in portfolios:
            command(
                "run",
                "--rm",
                "--no-deps",
                "-e",
                f"DB_NAME={target}",
                "trading",
                "python",
                "manage.py",
                "reconcile",
                portfolio,
            )
        print(
            json.dumps(
                {
                    "status": "passed",
                    "counts": after.decode().strip(),
                    "portfolios": len(portfolios),
                    "restore_seconds": round(time.monotonic() - start, 2),
                }
            )
        )
    finally:
        if created:
            command("exec", "-T", "postgres", "dropdb", "-U", "postgres", target)


if __name__ == "__main__":
    main()
