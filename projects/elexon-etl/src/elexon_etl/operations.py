"""Bounded, serial operations; no scheduler, queue or metadata database."""

from datetime import datetime, timedelta, timezone

from .events import emit
from .pipeline import checksum, run_partition
from .storage import LocalStore, load_json


def dates(start, end, maximum):
    if end < start or (end - start).days >= maximum:
        raise ValueError(f"Choose an inclusive date range of 1–{maximum} days")
    if end >= datetime.now(timezone.utc).date():
        raise ValueError("Choose completed UTC dates")
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def run_range(archive, store, datasets, days, refresh=False):
    for day in days:
        for dataset in datasets:
            run_partition(archive, store, dataset, day, skip_complete=not refresh)


def published_paths(store, datasets, days, workspace, max_download_bytes=512 * 1024 * 1024):
    paths = []
    downloaded = 0
    for day in days:
        for dataset in datasets:
            manifest = load_json(
                store, f"metadata/dataset={dataset}/date={day}/complete.json", workspace
            )
            if not manifest or manifest.get("state") != "complete":
                raise ValueError(f"Missing completed partition: {dataset}/{day}")
            if isinstance(store, LocalStore):
                path = store._path(manifest["output_key"])
                if not path.is_file():
                    raise ValueError(f"Missing output: {dataset}/{day}")
            else:
                downloaded += manifest["output_bytes"]
                if downloaded > max_download_bytes:
                    raise ValueError(
                        "Azure query exceeds 512 MiB download bound; narrow the date range"
                    )
                path = workspace / f"{dataset}-{day}.parquet"
                if not store.get(manifest["output_key"], path):
                    raise ValueError(f"Missing output: {dataset}/{day}")
            if checksum(path) != manifest["output_sha256"]:
                raise ValueError(f"Corrupt published output: {dataset}/{day}")
            paths.append(str(path))
    return paths


def cleanup_partition(store, dataset, day, workspace, apply=False, retention_days=7):
    """Only old, unpublished Parquet generations. Raw and audit records are retained."""
    if retention_days < 7:
        raise ValueError("Retention must be at least seven days")
    partition = f"dataset={dataset}/date={day}"
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = []
    with store.lock(partition) as check_lock:
        manifest = load_json(store, f"metadata/{partition}/complete.json", workspace)
        if not manifest or manifest.get("state") != "complete":
            raise ValueError("Cleanup requires a completed publication")
        current = load_json(store, f"metadata/{partition}/attempt.json", workspace) or {}
        protected = {manifest["output_key"], current.get("output_key")}
        prefix = f"curated/{partition}/"
        for key, modified in store.list_objects(prefix):
            # Restrict deletes to known generated Parquet paths, not arbitrary object prefixes.
            suffix = key.removeprefix(prefix).split("/")
            if (
                len(suffix) != 2
                or len(suffix[0]) != 32
                or any(c not in "0123456789abcdef" for c in suffix[0])
                or suffix[1] != "part-00000.parquet"
            ):
                continue
            if key not in protected and modified < cutoff:
                if apply:
                    check_lock()
                    store.delete(key)
                emit("cleanup_deleted" if apply else "cleanup_candidate", key=key)
                removed.append(key)
    return removed
