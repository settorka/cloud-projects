import json
from datetime import date, datetime, timezone

import pytest
from test_operations import RangeArchive

from elexon_etl import workflows


def test_daily_plan_is_json_and_anchored_to_run_interval(tmp_path):
    plan = workflows.make_plan(
        "daily", reference=datetime(2025, 1, 4, 3, tzinfo=timezone.utc), root=tmp_path
    )
    assert json.loads(json.dumps(plan)) == plan
    assert plan["start_date"] == "2025-01-01"
    assert plan["end_date"] == "2025-01-03"
    assert len(plan["partitions"]) == 6
    assert plan["refresh"] is True


@pytest.mark.parametrize(
    "command,kwargs",
    [
        ("run", {"start_date": "2025-01-01", "end_date": "2025-01-08"}),
        ("cleanup", {"start_date": "2025-01-01", "end_date": "2025-01-08"}),
        ("daily", {"source_date": "2025-01-01"}),
        ("daily", {"lookback_days": 0}),
        ("run", {"storage": "azure"}),
        ("run", {"dataset": "unknown"}),
        ("run", {"apply": True}),
        ("run", {"sql": "SELECT 1"}),
        ("run", {"start_date": "2025-01-01"}),
    ],
)
def test_invalid_plans_do_not_open_storage(monkeypatch, command, kwargs):
    monkeypatch.setattr(workflows, "open_store", lambda _: pytest.fail("Opened storage"))
    with pytest.raises(ValueError):
        workflows.make_plan(command, **kwargs)


def test_task_retry_reuses_completed_partition_and_returns_small_summary(tmp_path):
    archive = RangeArchive()
    plan = workflows.make_plan("run", source_date="2025-01-01", root=tmp_path)
    first = workflows.process_partition(plan, plan["partitions"][0], lambda: archive)
    second = workflows.process_partition(plan, plan["partitions"][0], lambda: archive)
    assert first == second
    assert archive.downloads == 1
    assert set(first) == {"dataset", "date", "output_key", "rows"}


def test_task_and_cli_runner_produce_identical_parquet(tmp_path, capsys):
    direct = workflows.make_plan("run", source_date="2025-01-01", root=tmp_path / "direct")
    tasks = workflows.make_plan("run", source_date="2025-01-01", root=tmp_path / "tasks")
    workflows.execute_plan(direct, archive_factory=RangeArchive)
    for partition in tasks["partitions"]:
        workflows.process_partition(tasks, partition, RangeArchive)
    for dataset in ("PN", "BOD"):

        def manifest(root):
            path = root / f"metadata/dataset={dataset}/date=2025-01-01/complete.json"
            return json.loads(path.read_text())

        a, b = manifest(tmp_path / "direct"), manifest(tmp_path / "tasks")
        assert a["output_sha256"] == b["output_sha256"]
        assert a["output_rows"] == b["output_rows"]
    query = workflows.make_plan("query", source_date=date(2025, 1, 1), root=tmp_path / "tasks")
    assert workflows.query_publications(query) == {"partitions": 2}
    assert "PN" in capsys.readouterr().out
