"""One dataset/date partition, preserving source snapshots rather than inventing final values."""

import hashlib
import json
import math
import os
import resource
import sys
import tempfile
import time
import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .events import emit
from .source import ARCHIVE
from .storage import load_json, save_json

TRANSFORM_VERSION = "1"


def code_checksum():
    return hashlib.sha256(
        b"".join(
            path.name.encode() + b"\0" + path.read_bytes()
            for path in sorted(Path(__file__).parent.glob("*.py"))
        )
    ).hexdigest()


def publication_coverage(sources, day):
    """A 48-slot UTC filename diagnostic, never a claim about upstream completeness."""
    expected = {
        (datetime.combine(day, datetime.min.time()) + timedelta(minutes=30 * i)).strftime("%H%M")
        for i in range(48)
    }
    observed = set()
    unexpected = []
    off_boundary = 0
    for source in sources:
        stamp = source.name.rsplit("/", 1)[-1].split("_")[1]
        try:
            parsed = datetime.strptime(stamp, "%Y%m%d%H%M")
            if len(stamp) != 12 or parsed.date() != day:
                raise ValueError("Filename timestamp outside partition")
        except ValueError:
            unexpected.append(source.name)
        else:
            # Publication can be a minute late; exact :00/:30 checks create false gaps.
            observed.add(f"{parsed.hour:02}{(parsed.minute // 30) * 30:02}")
            off_boundary += parsed.minute not in (0, 30)
    return {
        "expected_filename_slots": 48,
        "observed_filename_slots": len(observed),
        "missing_filename_slots": sorted(expected - observed),
        "unexpected_filename_count": len(unexpected),
        "off_boundary_filename_count": off_boundary,
    }


SCHEMA = pa.schema(
    [
        ("record_id", pa.string()),
        ("dataset", pa.string()),
        ("source_file_date", pa.date32()),
        ("settlement_date", pa.date32()),
        ("settlement_period", pa.int16()),
        ("time_from", pa.timestamp("ms", tz="UTC")),
        ("time_to", pa.timestamp("ms", tz="UTC")),
        ("bm_unit", pa.string()),
        ("national_grid_bm_unit", pa.string()),
        ("level_from", pa.float64()),
        ("level_to", pa.float64()),
        ("pair_id", pa.int32()),
        ("bid", pa.float64()),
        ("offer", pa.float64()),
        ("source_file", pa.string()),
        ("source_sha256", pa.string()),
        ("source_row", pa.int32()),
        ("transform_version", pa.string()),
    ]
)
COMMON = {
    "dataset",
    "settlementDate",
    "settlementPeriod",
    "timeFrom",
    "timeTo",
    "levelFrom",
    "levelTo",
    "nationalGridBmUnit",
    "bmUnit",
}


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must have timezone")
    return parsed.astimezone(timezone.utc)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Expected finite numeric value")
    return float(value)


def records(path, dataset, day, source_name, digest):
    source = json.loads(path.read_bytes())
    if not isinstance(source, list) or not source or len(source) > 100000:
        raise ValueError("Expected 1..100000 source records per file")
    result = []
    expected = COMMON | ({"pairId", "bid", "offer"} if dataset == "BOD" else set())
    for index, row in enumerate(source):
        try:
            if not isinstance(row, dict) or set(row) != expected:
                raise ValueError("Source fields differ from versioned schema")
            if row["dataset"] != dataset:
                raise ValueError("Dataset mismatch")
            period = row["settlementPeriod"]
            if type(period) is not int or not 1 <= period <= 50:
                raise ValueError("Invalid GB settlement period")
            start, end = timestamp(row["timeFrom"]), timestamp(row["timeTo"])
            if end < start:
                raise ValueError("Negative interval")
            for field in ("bmUnit", "nationalGridBmUnit"):
                # Elexon can publish a National Grid ID before the Elexon mapping exists.
                if field == "bmUnit" and row[field] is None:
                    continue
                if not isinstance(row[field], str) or not row[field].strip():
                    raise ValueError("Missing unit identifier")
            pair = row.get("pairId")
            if dataset == "BOD" and (type(pair) is not int or not -(2**31) <= pair < 2**31):
                raise ValueError("Invalid pairId")
            result.append(
                {
                    "record_id": hashlib.sha256(
                        f"{source_name}:{digest}:{index}".encode()
                    ).hexdigest(),
                    "dataset": dataset,
                    "source_file_date": day,
                    "settlement_date": date.fromisoformat(row["settlementDate"]),
                    "settlement_period": period,
                    "time_from": start,
                    "time_to": end,
                    "bm_unit": row["bmUnit"],
                    "national_grid_bm_unit": row["nationalGridBmUnit"],
                    "level_from": number(row["levelFrom"]),
                    "level_to": number(row["levelTo"]),
                    "pair_id": pair,
                    "bid": number(row["bid"]) if dataset == "BOD" else None,
                    "offer": number(row["offer"]) if dataset == "BOD" else None,
                    "source_file": source_name,
                    "source_sha256": digest,
                    "source_row": index,
                    "transform_version": TRANSFORM_VERSION,
                }
            )
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ValueError(f"Invalid source row {index}: {exc}") from exc
    return pa.Table.from_pylist(result, schema=SCHEMA)


def run_partition(archive, store, dataset, day, skip_complete=False):
    if dataset not in {"PN", "BOD"}:
        raise ValueError("Only PN and BOD are supported")
    if day >= datetime.now(timezone.utc).date():
        raise ValueError("Use a completed UTC source-file date")
    partition = f"dataset={dataset}/date={day.isoformat()}"
    attempt_key = f"metadata/{partition}/attempt.json"
    published_key = f"metadata/{partition}/complete.json"
    started = time.monotonic()
    with store.lock(partition) as check_lock, tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        previous = load_json(store, attempt_key, work) or {}
        publication = load_json(store, published_key, work) or {}
        if (
            skip_complete
            and publication.get("state") == "complete"
            and previous.get("state") == "complete"
            and previous.get("generation") == publication.get("generation")
            and publication.get("transform_version") == TRANSFORM_VERSION
            and publication.get("code_sha256") == code_checksum()
            and store.get(publication["output_key"], work / "verify.parquet")
            and checksum(work / "verify.parquet") == publication["output_sha256"]
        ):
            emit(
                "partition_skipped",
                dataset=dataset,
                source_file_date=str(day),
                run_id=publication["generation"],
            )
            return publication
        cached = {item["name"]: item for item in previous.get("files", [])}
        manifest = {
            "state": "running",
            "dataset": dataset,
            "source_file_date": str(day),
            "generation": uuid.uuid4().hex,
            "transform_version": TRANSFORM_VERSION,
            "source_archive": ARCHIVE,
            "code_sha256": code_checksum(),
            "image_digest": os.getenv("PIPELINE_IMAGE_DIGEST"),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "files": [],
            "input_rows": 0,
            "output_rows": 0,
            "raw_bytes": 0,
            "downloads": 0,
            "reused_files": 0,
            "unmapped_bm_unit_rows": 0,
            "attribution": f"Contains BMRS data © Elexon Limited copyright and database right {datetime.now(timezone.utc).year}.",
        }

        def persist():
            check_lock()
            # One retained file per attempt; checkpoints survive even a hard kill.
            save_json(
                store,
                f"metadata/{partition}/attempts/{manifest['generation']}.json",
                manifest,
                work,
            )
            save_json(store, attempt_key, manifest, work)

        emit(
            "partition_started",
            dataset=dataset,
            source_file_date=str(day),
            run_id=manifest["generation"],
        )
        try:
            # Preserve old file checkpoints if discovery fails or the process is killed early.
            manifest["files"] = list(cached.values())
            persist()
            sources = archive.discover(dataset, day)
            manifest["coverage"] = publication_coverage(sources, day)
            manifest["discovered_files"] = len(sources)
            manifest["files"] = [
                {
                    **(
                        cached.get(source.name, {})
                        if cached.get(source.name, {}).get("etag") == source.etag
                        and cached.get(source.name, {}).get("size") == source.size
                        else {}
                    ),
                    **asdict(source),
                    "state": "pending",
                }
                for source in sources
            ]
            persist()
            output_path = work / "part-00000.parquet"
            with pq.ParquetWriter(output_path, SCHEMA, compression="zstd") as writer:
                for source in sources:
                    check_lock()
                    entry = asdict(source)
                    manifest["files"] = [f for f in manifest["files"] if f["name"] != source.name]
                    manifest["files"].append(entry)
                    old = cached.get(source.name, {})
                    raw_path = work / "source.json"
                    reusable = (
                        old.get("etag") == source.etag
                        and old.get("size") == source.size
                        and old.get("raw_key")
                        and old.get("sha256")
                    )
                    if (
                        reusable
                        and store.get(old["raw_key"], raw_path)
                        and checksum(raw_path) == old["sha256"]
                    ):
                        digest = old["sha256"]
                        manifest["reused_files"] += 1
                    else:
                        digest = archive.download(source, raw_path)
                        manifest["downloads"] += 1
                        # Store only new/repaired raw content, not every cached file after a miss.
                        raw_key = f"raw/{partition}/{hashlib.sha256(source.name.encode()).hexdigest()}/{digest}.json"
                        store.put(raw_key, raw_path)
                    raw_key = f"raw/{partition}/{hashlib.sha256(source.name.encode()).hexdigest()}/{digest}.json"
                    entry.update(sha256=digest, raw_key=raw_key, state="downloaded")
                    persist()  # Raw is durable before any transformation; interrupted runs reuse it.
                    try:
                        table = records(raw_path, dataset, day, source.name, digest)
                    except ValueError:
                        entry["state"] = "rejected"
                        raise
                    writer.write_table(table)
                    entry.update(state="processed", rows=table.num_rows)
                    manifest["input_rows"] += table.num_rows
                    manifest["output_rows"] += table.num_rows
                    manifest["raw_bytes"] += source.size
                    manifest["unmapped_bm_unit_rows"] += table.column("bm_unit").null_count
                    persist()
            output_key = f"curated/{partition}/{manifest['generation']}/part-00000.parquet"
            store.put(output_key, output_path)
            manifest.update(
                state="complete",
                output_key=output_key,
                output_sha256=checksum(output_path),
                output_bytes=output_path.stat().st_size,
                wall_seconds=round(time.monotonic() - started, 3),
                process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                * (1 if sys.platform == "darwin" else 1024),
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            persist()
            # Old publication remains usable until this small pointer is replaced atomically.
            check_lock()
            save_json(store, published_key, manifest, work)
            emit(
                "partition_succeeded",
                **{key: value for key, value in manifest.items() if key != "files"},
                run_id=manifest["generation"],
            )
            if (
                manifest["coverage"]["missing_filename_slots"]
                or manifest["coverage"]["unexpected_filename_count"]
            ):
                emit(
                    "coverage_warning",
                    dataset=dataset,
                    source_file_date=str(day),
                    run_id=manifest["generation"],
                    **manifest["coverage"],
                )
            return manifest
        except BaseException as exc:
            manifest.update(
                state="failed",
                error_type=type(exc).__name__,
                error=str(exc)[:500],
                ended_at=datetime.now(timezone.utc).isoformat(),
                wall_seconds=round(time.monotonic() - started, 3),
            )
            for entry in manifest["files"]:
                if entry.get("state", "pending") == "pending":
                    entry["state"] = "failed"
            emit(
                "partition_failed",
                dataset=dataset,
                source_file_date=str(day),
                run_id=manifest["generation"],
                error_type=type(exc).__name__,
            )
            try:
                persist()
            except Exception:
                # Preserve the original error if storage or lease ownership was lost.
                pass
            raise
