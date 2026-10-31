import argparse
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .events import emit
from .operations import cleanup_partition, dates, published_paths, run_range
from .source import Archive
from .storage import AzureStore, LocalStore


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
    if args.storage == "azure" and not args.account:
        parser.error("--account or AZURE_STORAGE_ACCOUNT is required for Azure")
    if args.date and (args.start_date or args.end_date):
        parser.error("Use --date or a start/end date range, not both")
    if bool(args.start_date) != bool(args.end_date):
        parser.error("Supply both --start-date and --end-date")
    if args.command != "cleanup" and args.apply:
        parser.error("--apply is only valid for cleanup")
    if args.command != "query" and args.sql:
        parser.error("--sql is only valid for query")
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    if args.command == "daily":
        if args.date or args.start_date:
            parser.error("Daily uses a rolling lookback; use run for explicit dates")
        if not 1 <= args.lookback_days <= 7:
            parser.error("--lookback-days must be 1–7")
        start, end = yesterday - timedelta(days=args.lookback_days - 1), yesterday
    else:
        start = args.start_date or args.date or yesterday
        end = args.end_date or start
    try:
        days = dates(start, end, 366 if args.command == "query" else 7)
    except ValueError as exc:
        parser.error(str(exc))
    datasets = ["PN", "BOD"] if args.dataset == "BOTH" else [args.dataset]
    store = (
        AzureStore(args.account, os.getenv("AZURE_CLIENT_ID"))
        if args.storage == "azure"
        else LocalStore(args.root)
    )
    emit(
        "invocation_started",
        command=args.command,
        datasets=datasets,
        start_date=str(start),
        end_date=str(end),
    )
    try:
        if args.command in {"run", "daily"}:
            archive = Archive()
            try:
                run_range(
                    archive, store, datasets, days, refresh=args.refresh or args.command == "daily"
                )
            finally:
                archive.close()
        else:
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                if args.command == "cleanup":
                    for day in days:
                        for dataset in datasets:
                            cleanup_partition(store, dataset, day, work, apply=args.apply)
                else:
                    import duckdb

                    paths = published_paths(store, datasets, days, work)
                    with duckdb.connect(config={"memory_limit": "512MB"}) as connection:
                        connection.read_parquet(paths, hive_partitioning=False).create_view(
                            "elexon"
                        )
                        sql = (
                            args.sql.read_text()
                            if args.sql
                            else (
                                "SELECT dataset, source_file_date, count(*) AS rows FROM elexon "
                                "GROUP BY ALL ORDER BY ALL"
                            )
                        )
                        print(connection.sql(sql))
        emit(
            "invocation_succeeded",
            command=args.command,
            datasets=datasets,
            start_date=str(start),
            end_date=str(end),
        )
    except BaseException as exc:
        emit("invocation_failed", command=args.command, error_type=type(exc).__name__)
        raise
    finally:
        store.close()


if __name__ == "__main__":
    main()
