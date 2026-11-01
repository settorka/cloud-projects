"""Scheduler-independent plans and task bodies shared by the CLI and Airflow.

Plans contain only JSON values. Files and clients stay in the task process, never
in Airflow XCom. Publication remains one atomic, leased dataset/date transaction.
"""

import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .events import emit
from .operations import cleanup_partition, dates, published_paths
from .pipeline import run_partition
from .source import Archive
from .storage import AzureStore, LocalStore

DEFAULT_SQL = (
    "SELECT dataset, source_file_date, count(*) AS rows FROM elexon GROUP BY ALL ORDER BY ALL"
)


def make_plan(
    command,
    *,
    dataset="BOTH",
    source_date=None,
    start_date=None,
    end_date=None,
    lookback_days=3,
    refresh=False,
    storage="local",
    root="data",
    account=None,
    apply=False,
    sql=None,
    reference=None,
):
    if command not in {"run", "daily", "query", "cleanup"}:
        raise ValueError("Unknown command")
    if dataset not in {"PN", "BOD", "BOTH"}:
        raise ValueError("Unknown dataset")
    if storage not in {"local", "azure"}:
        raise ValueError("Unknown storage")
    if storage == "azure" and not account:
        raise ValueError("Azure storage requires an account")
    if source_date and (start_date or end_date):
        raise ValueError("Use --date or a start/end date range, not both")
    if bool(start_date) != bool(end_date):
        raise ValueError("Supply both --start-date and --end-date")
    if apply and command != "cleanup":
        raise ValueError("--apply is only valid for cleanup")
    if sql is not None and command != "query":
        raise ValueError("--sql is only valid for query")
    reference = reference or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        raise ValueError("Reference time must be timezone-aware")
    yesterday = reference.astimezone(timezone.utc).date() - timedelta(days=1)
    if command == "daily":
        if source_date or start_date:
            raise ValueError("Daily uses a rolling lookback; use run for explicit dates")
        if not 1 <= lookback_days <= 7:
            raise ValueError("--lookback-days must be 1–7")
        start, end = yesterday - timedelta(days=lookback_days - 1), yesterday
    else:
        start = date.fromisoformat(str(start_date or source_date or yesterday))
        end = date.fromisoformat(str(end_date or start))
    days = dates(start, end, 366 if command == "query" else 7)
    datasets = ["PN", "BOD"] if dataset == "BOTH" else [dataset]
    return {
        "command": command,
        "datasets": datasets,
        "start_date": str(start),
        "end_date": str(end),
        "partitions": [{"dataset": ds, "date": str(day)} for day in days for ds in datasets],
        "refresh": refresh or command == "daily",
        "storage": storage,
        "root": str(Path(root).resolve()),
        "account": account,
        "apply": apply,
        "sql": sql if sql is not None else DEFAULT_SQL,
    }


def invocation_event(event, plan):
    emit(event, **{key: plan[key] for key in ("command", "datasets", "start_date", "end_date")})


def open_store(plan):
    return (
        AzureStore(plan["account"], os.getenv("AZURE_CLIENT_ID"))
        if plan["storage"] == "azure"
        else LocalStore(plan["root"])
    )


def process_partition(plan, partition, archive_factory=None):
    """Retry unit: publish one partition, or leave the previous publication intact."""
    store = open_store(plan)
    try:
        day = date.fromisoformat(partition["date"])
        if plan["command"] == "cleanup":
            with tempfile.TemporaryDirectory() as tmp:
                removed = cleanup_partition(
                    store, partition["dataset"], day, Path(tmp), apply=plan["apply"]
                )
            return {**partition, "eligible_outputs": len(removed), "applied": plan["apply"]}
        archive = (archive_factory or Archive)()
        try:
            result = run_partition(
                archive, store, partition["dataset"], day, skip_complete=not plan["refresh"]
            )
            return {**partition, "output_key": result["output_key"], "rows": result["output_rows"]}
        finally:
            archive.close()
    finally:
        store.close()


def query_publications(plan):
    """Query the whole selection once; preserve cross-partition SQL semantics."""
    import duckdb

    store = open_store(plan)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            days = dates(
                date.fromisoformat(plan["start_date"]), date.fromisoformat(plan["end_date"]), 366
            )
            paths = published_paths(store, plan["datasets"], days, Path(tmp))
            with duckdb.connect(config={"memory_limit": "512MB"}) as connection:
                connection.read_parquet(paths, hive_partitioning=False).create_view("elexon")
                print(connection.sql(plan["sql"]))
        return {"partitions": len(plan["partitions"])}
    finally:
        store.close()


def execute_plan(plan, archive_factory=None):
    """CLI runner; Airflow schedules these same bodies as individual tasks."""
    invocation_event("invocation_started", plan)
    try:
        if plan["command"] == "query":
            query_publications(plan)
        else:
            for partition in plan["partitions"]:
                process_partition(plan, partition, archive_factory)
        invocation_event("invocation_succeeded", plan)
    except BaseException as exc:
        emit("invocation_failed", command=plan["command"], error_type=type(exc).__name__)
        raise
