"""Real SQLite-backed DagRuns against preseeded fixtures, without Elexon/Azure IO.

Exercises mapping, cache replay, cross-partition query, dry-run/applied cleanup,
and rejection of an invalid backfill. Partition transforms are tested separately.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from elexon_etl.pipeline import run_partition
from elexon_etl.source import SourceFile
from elexon_etl.storage import LocalStore

PROJECT = Path(__file__).resolve().parents[1]


class FixtureArchive:
    def close(self):
        pass

    def discover(self, dataset, day):
        raw = (PROJECT / "tests/fixtures" / f"{dataset.lower()}.json").read_bytes()
        return [SourceFile(f"data/{dataset}/{dataset}_{day:%Y%m%d}0000_test.json", len(raw), "v1")]

    def download(self, source, destination):
        dataset = source.name.split("/")[1]
        raw = (PROJECT / "tests/fixtures" / f"{dataset.lower()}.json").read_bytes()
        destination.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()


def main():
    (PROJECT / "data").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="airflow-smoke-", dir=PROJECT / "data") as tmp:
        home = Path(tmp)
        root = home / "store"
        os.environ.update(
            {
                "AIRFLOW_HOME": str(home),
                "AIRFLOW__CORE__DAGS_FOLDER": str(PROJECT / "dags"),
                "AIRFLOW__CORE__LOAD_EXAMPLES": "False",
                "AIRFLOW__CORE__EXECUTOR": "SequentialExecutor",
                "ELEXON_ROOT": str(root),
                "ELEXON_STORAGE": "local",
            }
        )
        with (home / "migrate.log").open("w") as log:
            subprocess.run(
                [sys.executable, "-m", "airflow", "db", "migrate"],
                check=True,
                stdout=log,
                stderr=subprocess.STDOUT,
            )

        import pendulum
        from airflow.models import DagBag

        store = LocalStore(root)
        archive = FixtureArchive()
        day = date(2025, 1, 1)
        old = run_partition(archive, store, "PN", day)
        old_path = root / old["output_key"]
        stamp = (datetime.now(timezone.utc) - timedelta(days=8)).timestamp()
        os.utime(old_path, (stamp, stamp))
        for selected in (day, day + timedelta(days=1)):
            for dataset in ("PN", "BOD"):
                run_partition(archive, store, dataset, selected)

        bag = DagBag(str(PROJECT / "dags"))
        assert not bag.import_errors, bag.import_errors
        conf = {"start_date": "2025-01-01", "end_date": "2025-01-02"}
        run = bag.dags["elexon_run"].test(run_conf=conf)
        assert run.state == "success", run.state
        processed = [ti for ti in run.get_task_instances() if ti.task_id == "process"]
        assert len(processed) == 4
        assert all(ti.state == "success" for ti in processed)
        # dag.test forks task processes; the patched fixture source is inherited.
        # Exercise actual daily refresh tasks, not mark-success substitutes.
        with patch("elexon_etl.workflows.Archive", FixtureArchive):
            daily = bag.dags["elexon_daily"].test(
                logical_date=pendulum.datetime(2025, 1, 3, 3, tz="UTC"),
                run_conf={"lookback_days": 1},
            )
        assert daily.state == "success"
        refreshed = json.loads(
            (root / "metadata/dataset=PN/date=2025-01-02/complete.json").read_text()
        )
        assert refreshed["downloads"] == 0
        assert refreshed["reused_files"] == 1
        assert bag.dags["elexon_query"].test(run_conf=conf).state == "success"
        assert bag.dags["elexon_cleanup"].test(run_conf=conf).state == "success"
        assert old_path.exists(), "Dry-run cleanup deleted data"
        assert bag.dags["elexon_cleanup"].test(run_conf={**conf, "apply": True}).state == "success"
        assert not old_path.exists(), "Applied cleanup did not delete the eligible old output"
        assert bag.dags["elexon_query"].test(run_conf=conf).state == "success"
        bad = {"start_date": "2025-01-01", "end_date": "2025-01-08"}
        failed = bag.dags["elexon_run"].test(run_conf=bad)
        assert failed.state == "failed"
        assert all(
            ti.state != "success" for ti in failed.get_task_instances() if ti.task_id == "complete"
        )
        print("Airflow smoke passed: mapped cache replay, query, cleanup and failure propagation")


if __name__ == "__main__":
    main()
