import hashlib
import json
from datetime import date
from pathlib import Path

import duckdb
import pytest

from elexon_etl.pipeline import run_partition
from elexon_etl.source import SourceFile
from elexon_etl.storage import LocalStore

DAY = date(2025, 1, 1)
FIXTURES = Path(__file__).parent / "fixtures"


class FakeArchive:
    def __init__(self, dataset="PN", count=2):
        raw = (FIXTURES / f"{dataset.lower()}.json").read_bytes()
        self.contents = {f"data/{dataset}/{dataset}_20250101{i:04}.json": raw for i in range(count)}
        self.downloads = []
        self.interrupt_at = None

    def discover(self, dataset, day):
        return [
            SourceFile(name, len(raw), hashlib.sha256(raw).hexdigest())
            for name, raw in self.contents.items()
        ]

    def download(self, source, destination):
        if source.name == self.interrupt_at:
            raise KeyboardInterrupt("Simulated process interruption")
        self.downloads.append(source.name)
        destination.write_bytes(self.contents[source.name])
        return hashlib.sha256(self.contents[source.name]).hexdigest()


def publication(root, dataset="PN"):
    return json.loads((root / f"metadata/dataset={dataset}/date={DAY}/complete.json").read_text())


def ids(root, manifest):
    with duckdb.connect() as db:
        return db.read_parquet(str(root / manifest["output_key"])).select("record_id").fetchall()


@pytest.mark.parametrize("dataset,rows", [("PN", 4), ("BOD", 2)])
def test_round_trip_and_replay(tmp_path, dataset, rows):
    archive = FakeArchive(dataset)
    store = LocalStore(tmp_path)
    first = run_partition(archive, store, dataset, DAY)
    assert first["output_rows"] == rows
    assert first["discovered_files"] == 2
    assert all(f["state"] == "processed" for f in first["files"])
    second = run_partition(archive, store, dataset, DAY)
    assert second["downloads"] == 0
    assert second["reused_files"] == 2
    assert sorted(ids(tmp_path, first)) == sorted(ids(tmp_path, second))
    assert len(set(ids(tmp_path, second))) == rows
    assert publication(tmp_path, dataset)["generation"] == second["generation"]


def test_resume_after_abrupt_interruption(tmp_path):
    archive = FakeArchive()
    archive.interrupt_at = list(archive.contents)[1]
    store = LocalStore(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        run_partition(archive, store, "PN", DAY)
    assert not (tmp_path / f"metadata/dataset=PN/date={DAY}/complete.json").exists()
    archive.interrupt_at = None
    result = run_partition(archive, store, "PN", DAY)
    assert result["reused_files"] == 1
    assert result["downloads"] == 1
    assert len(archive.downloads) == 2


def test_bad_revision_does_not_replace_publication(tmp_path):
    archive = FakeArchive()
    store = LocalStore(tmp_path)
    first = run_partition(archive, store, "PN", DAY)
    source_name = list(archive.contents)[0]
    rows = json.loads(archive.contents[source_name])
    rows[0]["levelFrom"] = "bad"
    archive.contents[source_name] = json.dumps(rows).encode()
    with pytest.raises(ValueError, match="finite numeric"):
        run_partition(archive, store, "PN", DAY)
    assert publication(tmp_path)["generation"] == first["generation"]
    failed = json.loads((tmp_path / f"metadata/dataset=PN/date={DAY}/attempt.json").read_text())
    assert failed["state"] == "failed"
    assert any(f["state"] == "rejected" for f in failed["files"])
    assert ids(tmp_path, publication(tmp_path)) == ids(tmp_path, first)


def test_changed_source_is_preserved_and_republished(tmp_path):
    archive = FakeArchive(count=1)
    store = LocalStore(tmp_path)
    first = run_partition(archive, store, "PN", DAY)
    name = next(iter(archive.contents))
    rows = json.loads(archive.contents[name])
    rows[0]["levelFrom"] = 999
    archive.contents[name] = json.dumps(rows).encode()
    second = run_partition(archive, store, "PN", DAY)
    assert second["downloads"] == 1
    assert (tmp_path / first["files"][0]["raw_key"]).is_file()
    assert (tmp_path / second["files"][0]["raw_key"]).is_file()
    assert ids(tmp_path, first) != ids(tmp_path, second)


def test_interrupt_after_revision_discovery_cannot_reuse_old_content(tmp_path):
    archive = FakeArchive(count=2)
    store = LocalStore(tmp_path)
    run_partition(archive, store, "PN", DAY)
    name = list(archive.contents)[1]
    rows = json.loads(archive.contents[name])
    rows[0]["levelFrom"] = 456
    archive.contents[name] = json.dumps(rows).encode()
    archive.interrupt_at = list(archive.contents)[0]
    # Force a miss on the first file, interrupting before the revised second file is visited.
    first = list(archive.contents)[0]
    archive.contents[first] += b" "
    with pytest.raises(KeyboardInterrupt):
        run_partition(archive, store, "PN", DAY)
    archive.interrupt_at = None
    result = run_partition(archive, store, "PN", DAY)
    assert result["downloads"] == 2
    with duckdb.connect() as db:
        values = (
            db.read_parquet(str(tmp_path / result["output_key"])).select("level_from").fetchall()
        )
    assert (456.0,) in values


def test_null_elexon_mapping_preserves_national_grid_id(tmp_path):
    archive = FakeArchive(count=1)
    name = next(iter(archive.contents))
    rows = json.loads(archive.contents[name])
    rows[0]["bmUnit"] = None
    archive.contents[name] = json.dumps(rows).encode()
    result = run_partition(archive, LocalStore(tmp_path), "PN", DAY)
    with duckdb.connect() as db:
        rows = (
            db.read_parquet(str(tmp_path / result["output_key"]))
            .filter("bm_unit IS NULL")
            .select("national_grid_bm_unit")
            .fetchall()
        )
    assert rows == [("DEMO-1",)]


def test_corrupt_cache_is_redownloaded(tmp_path):
    archive = FakeArchive(count=1)
    store = LocalStore(tmp_path)
    first = run_partition(archive, store, "PN", DAY)
    (tmp_path / first["files"][0]["raw_key"]).write_bytes(b"corrupt")
    result = run_partition(archive, store, "PN", DAY)
    assert result["downloads"] == 1
    assert ids(tmp_path, first) == ids(tmp_path, result)


def test_lock_rejects_competing_writer(tmp_path):
    store = LocalStore(tmp_path)
    with store.lock(f"dataset=PN/date={DAY}"):
        with pytest.raises(BlockingIOError):
            run_partition(FakeArchive(), store, "PN", DAY)


@pytest.mark.parametrize(
    "field,value",
    [
        ("settlementPeriod", 51),
        ("levelFrom", True),
        ("timeFrom", "2025-01-01T01:00:00"),
        ("newField", "schema drift"),
        ("timeTo", "2024-01-01T00:00:00Z"),
    ],
)
def test_invalid_rows_never_publish(tmp_path, field, value):
    archive = FakeArchive(count=1)
    name = next(iter(archive.contents))
    rows = json.loads(archive.contents[name])
    rows[0][field] = value
    archive.contents[name] = json.dumps(rows).encode()
    with pytest.raises(ValueError):
        run_partition(archive, LocalStore(tmp_path), "PN", DAY)
    assert not (tmp_path / f"metadata/dataset=PN/date={DAY}/complete.json").exists()


def test_cannot_escape_storage_root(tmp_path):
    with pytest.raises(ValueError):
        LocalStore(tmp_path).get("../outside", tmp_path / "read")
