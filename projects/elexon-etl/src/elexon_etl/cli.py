import argparse
import os
from datetime import date, datetime, timezone
from pathlib import Path

from .source import Archive
from .workflows import execute_plan, make_plan


def main():
    parser = argparse.ArgumentParser(description="Bounded PN/BOD source-snapshot ingestion")
    parser.add_argument("command", choices=["run", "daily", "query", "cleanup"])
    parser.add_argument("--dataset", choices=["PN", "BOD", "BOTH"], default="BOTH")
    parser.add_argument("--date", type=date.fromisoformat, help="One UTC source-file date")
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument(
        "--refresh", action="store_true", help="Rediscover and rebuild completed partitions"
    )
    parser.add_argument(
        "--lookback-days", type=int, default=3, help="Daily revision/gap window, 1–7 days"
    )
    parser.add_argument("--storage", choices=["local", "azure"], default="local")
    parser.add_argument("--root", default="data", help="Local storage root")
    parser.add_argument("--account", default=os.getenv("AZURE_STORAGE_ACCOUNT"))
    parser.add_argument("--sql", type=Path, help="Query file; query command only")
    parser.add_argument(
        "--apply", action="store_true", help="Delete eligible old curated generations"
    )
    args = parser.parse_args()
    try:
        plan = make_plan(
            args.command,
            dataset=args.dataset,
            source_date=args.date,
            start_date=args.start_date,
            end_date=args.end_date,
            lookback_days=args.lookback_days,
            refresh=args.refresh,
            storage=args.storage,
            root=args.root,
            account=args.account,
            apply=args.apply,
            sql=args.sql.read_text() if args.sql else None,
            reference=datetime.now(timezone.utc),
        )
    except ValueError as exc:
        parser.error(str(exc))
    execute_plan(plan, archive_factory=Archive)


if __name__ == "__main__":
    main()
