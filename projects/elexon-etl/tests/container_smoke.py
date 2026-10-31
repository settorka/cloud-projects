"""Offline end-to-end image check: real storage, Parquet, DuckDB, rerun and both datasets."""

import hashlib
import tempfile
from datetime import date
from pathlib import Path

import duckdb

from elexon_etl.operations import published_paths
from elexon_etl.pipeline import run_partition
from elexon_etl.source import SourceFile
from elexon_etl.storage import LocalStore


class FixtureArchive:
    def __init__(self, dataset):
        self.raw = (Path(__file__).parent / "fixtures" / f"{dataset.lower()}.json").read_bytes()

    def discover(self, dataset, day):
        return [
            SourceFile(
                f"data/{dataset}/{dataset}_{day:%Y%m%d}0000_fixture.json",
                len(self.raw),
                "fixture-revision",
            )
        ]

    def download(self, source, path):
        path.write_bytes(self.raw)
        return hashlib.sha256(self.raw).hexdigest()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = LocalStore(root / "storage")
        day = date(2025, 1, 1)
        for dataset, rows in [("PN", 2), ("BOD", 1)]:
            archive = FixtureArchive(dataset)
            result = run_partition(archive, store, dataset, day)
            replay = run_partition(archive, store, dataset, day)
            assert result["output_rows"] == rows
            assert replay["downloads"] == 0 and replay["reused_files"] == 1
        paths = published_paths(store, ["PN", "BOD"], [day], root)
        with duckdb.connect() as connection:
            connection.read_parquet(paths, hive_partitioning=False).create_view("elexon")
            assert connection.sql("SELECT count(*) FROM elexon").fetchone()[0] == 3
            assert connection.sql("SELECT count(DISTINCT record_id) FROM elexon").fetchone()[0] == 3
        print("Container smoke check passed: PN/BOD, Parquet, DuckDB and cache reuse")
