import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

from elexon_etl.operations import cleanup_partition, dates, published_paths, run_range
from elexon_etl.pipeline import publication_coverage, run_partition
from elexon_etl.source import SourceFile
from elexon_etl.storage import LocalStore

FIXTURES = Path(__file__).parent / "fixtures"
DAY = date(2025, 1, 1)


class RangeArchive:
    def __init__(self):
        self.downloads = 0
        self.fail = None
        self.raw = {}

    def discover(self, dataset, day):
        if self.fail == (dataset, day):
            raise RuntimeError("Source unavailable")
        name = f"data/{dataset}/{dataset}_{day:%Y%m%d}0000_fixture.json"
        content = (FIXTURES / f"{dataset.lower()}.json").read_bytes()
        self.raw[name] = content
        return [SourceFile(name, len(content), "revision-1")]

    def download(self, source, destination):
        self.downloads += 1
        destination.write_bytes(self.raw[source.name])
        return hashlib.sha256(self.raw[source.name]).hexdigest()

    def close(self):
        pass


def test_range_stops_on_failure_then_resumes_and_queries_only_current_outputs(tmp_path):
    store, archive = LocalStore(tmp_path / "store"), RangeArchive()
    selected = dates(DAY, DAY + timedelta(days=2), 7)
    archive.fail = ("PN", selected[1])
    with pytest.raises(RuntimeError):
        run_range(archive, store, ["PN", "BOD"], selected)
    assert archive.downloads == 2
    archive.fail = None
    run_range(archive, store, ["PN", "BOD"], selected)
    assert archive.downloads == 6
    # Explicit refresh creates older generations; query still returns each source record once.
    run_range(archive, store, ["PN", "BOD"], selected, refresh=True)
    paths = published_paths(store, ["PN", "BOD"], selected, tmp_path)
    with duckdb.connect() as db:
        relation = db.read_parquet(paths, hive_partitioning=False)
        assert relation.count("*").fetchone()[0] == 9
        assert relation.aggregate("count(DISTINCT record_id)").fetchone()[0] == 9


def test_audit_history_and_events_survive_failure(tmp_path, capsys):
    store, archive = LocalStore(tmp_path / "store"), RangeArchive()
    first = run_partition(archive, store, "PN", DAY)
    archive.fail = ("PN", DAY)
    with pytest.raises(RuntimeError):
        run_partition(archive, store, "PN", DAY)
    history = list((store.root / f"metadata/dataset=PN/date={DAY}/attempts").glob("*.json"))
    manifests = [json.loads(path.read_text()) for path in history]
    assert sorted(item["state"] for item in manifests) == ["complete", "failed"]
    assert any(item["generation"] == first["generation"] for item in manifests)
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {event["event"] for event in events} >= {
        "partition_started",
        "partition_succeeded",
        "partition_failed",
    }
    assert all(event.get("run_id") for event in events)


def test_query_requires_every_requested_partition_and_valid_checksum(tmp_path):
    store = LocalStore(tmp_path / "store")
    result = run_partition(RangeArchive(), store, "PN", DAY)
    with pytest.raises(ValueError, match="Missing completed"):
        published_paths(store, ["PN", "BOD"], [DAY], tmp_path)
    store._path(result["output_key"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Corrupt"):
        published_paths(store, ["PN"], [DAY], tmp_path)


def test_cleanup_is_dry_run_and_keeps_published_raw_and_audit(tmp_path):
    store, archive = LocalStore(tmp_path / "store"), RangeArchive()
    old = run_partition(archive, store, "PN", DAY)
    current = run_partition(archive, store, "PN", DAY)
    timestamp = (datetime.now(timezone.utc) - timedelta(days=8)).timestamp()
    for item in (old, current):
        os.utime(store._path(item["output_key"]), (timestamp, timestamp))
    assert cleanup_partition(store, "PN", DAY, tmp_path) == [old["output_key"]]
    assert store._path(old["output_key"]).is_file()
    assert cleanup_partition(store, "PN", DAY, tmp_path, apply=True) == [old["output_key"]]
    assert not store._path(old["output_key"]).exists()
    assert store._path(current["output_key"]).exists()
    assert store._path(old["files"][0]["raw_key"]).exists()
    assert store._path(f"metadata/dataset=PN/date={DAY}/attempts/{old['generation']}.json").exists()


def test_filename_slot_coverage_is_diagnostic():
    files = [
        SourceFile(f"data/PN/PN_20250101{hour:02}{minute:02}_test.json", 1, "v1")
        for hour in range(24)
        for minute in (0, 30)
    ]
    complete = publication_coverage(files, DAY)
    assert complete["missing_filename_slots"] == []
    missing = publication_coverage(files[:-1], DAY)
    assert missing["missing_filename_slots"] == ["2330"]
    delayed = [
        SourceFile(f"data/PN/PN_20250101{hour:02}{minute:02}_test.json", 1, "v1")
        for hour in range(24)
        for minute in (1, 31)
    ]
    delayed_coverage = publication_coverage(delayed, DAY)
    assert delayed_coverage["missing_filename_slots"] == []
    assert delayed_coverage["off_boundary_filename_count"] == 48


@pytest.mark.parametrize(
    "start,end,maximum",
    [
        (DAY, DAY + timedelta(days=7), 7),
        (DAY, DAY - timedelta(days=1), 7),
        (DAY, date(2999, 1, 1), 1000000),
    ],
)
def test_invalid_ranges_fail_before_processing(start, end, maximum):
    with pytest.raises(ValueError):
        dates(start, end, maximum)


def test_cli_failure_never_emits_a_successful_invocation(tmp_path, capsys, monkeypatch):
    from elexon_etl import cli

    archive = RangeArchive()
    archive.fail = ("BOD", DAY)
    monkeypatch.setattr(cli, "Archive", lambda: archive)
    monkeypatch.setattr(
        "sys.argv", ["elexon-etl", "run", "--date", str(DAY), "--root", str(tmp_path)]
    )
    with pytest.raises(RuntimeError):
        cli.main()
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert any(e["event"] == "invocation_failed" for e in events)
    assert not any(e["event"] == "invocation_succeeded" for e in events)


def test_daily_refreshes_both_datasets_for_the_rolling_window(tmp_path, capsys, monkeypatch):
    from elexon_etl import cli

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2025, 1, 4, tzinfo=timezone.utc)

    archive = RangeArchive()
    monkeypatch.setattr(cli, "datetime", FixedDatetime)
    monkeypatch.setattr(cli, "Archive", lambda: archive)
    monkeypatch.setattr("sys.argv", ["elexon-etl", "daily", "--root", str(tmp_path)])
    cli.main()
    assert archive.downloads == 6
    cli.main()
    assert archive.downloads == 6
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    completed = [e for e in events if e["event"] == "invocation_succeeded"]
    assert len(completed) == 2
    assert completed[-1]["datasets"] == ["PN", "BOD"]
    assert completed[-1]["start_date"] == "2025-01-01"
    assert completed[-1]["end_date"] == "2025-01-03"


def test_range_repairs_a_corrupt_completed_output(tmp_path):
    archive, store = RangeArchive(), LocalStore(tmp_path / "store")
    result = run_partition(archive, store, "PN", DAY)
    store._path(result["output_key"]).write_bytes(b"corrupt")
    run_range(archive, store, ["PN"], [DAY])
    assert archive.downloads == 1
    assert published_paths(store, ["PN"], [DAY], tmp_path)
