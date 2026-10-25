"""Restore a local dump into a unique rehearsal database, verify, and clean it up."""

import argparse
import json
import subprocess
import time
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env.example")
    args = parser.parse_args()
    base = ["docker", "compose", "--env-file", args.env_file]
    target = "restore_" + uuid.uuid4().hex[:12]

    def command(*argv, input=None):
        return subprocess.run([*base, *argv], input=input, capture_output=True, check=True).stdout

    query = "SELECT (SELECT count(*) FROM trading.app_trade), (SELECT count(*) FROM trading.app_traderevision), (SELECT count(*) FROM market_data.app_marketrevision), (SELECT count(*) FROM valuation.app_valuationrun)"
    start = time.monotonic()
    created = False
    try:
        # Caller must quiesce writers for a meaningful cross-check.
        dump = command(
            "exec", "-T", "postgres", "pg_dump", "-U", "postgres", "-d", "renewables", "-Fc"
        )
        before = command(
            "exec", "-T", "postgres", "psql", "-U", "postgres", "-d", "renewables", "-Atc", query
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
