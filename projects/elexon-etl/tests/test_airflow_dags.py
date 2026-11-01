"""Real SDK graph/serialization checks; skipped in the lightweight CLI install."""

from pathlib import Path

import pytest

pytest.importorskip("airflow")


def test_dags_parse_and_serialize_without_source_or_storage_io(monkeypatch, tmp_path):
    from airflow.models import DagBag
    from airflow.serialization.serialized_objects import DagSerialization

    from elexon_etl import workflows

    monkeypatch.setattr(workflows, "open_store", lambda _: pytest.fail("Parse opened storage"))
    monkeypatch.setattr(workflows, "Archive", lambda: pytest.fail("Parse opened source"))
    folder = Path(__file__).resolve().parents[1] / "dags"
    bag = DagBag(str(folder))
    assert not bag.import_errors
    assert set(bag.dags) == {"elexon_daily", "elexon_run", "elexon_query", "elexon_cleanup"}
    for name, dag in bag.dags.items():
        dag.validate()
        serialized = DagSerialization.serialize_dag(dag)
        assert serialized
        assert dag.max_active_runs == dag.max_active_tasks == 1
        assert dag.catchup is False
        assert dag.is_paused_upon_creation is True
        assert dag.get_task("complete").trigger_rule == "all_success"
        worker = dag.get_task("query" if name == "elexon_query" else "process")
        assert worker.upstream_task_ids == (
            {"plan"} if name == "elexon_query" else {"plan", "partitions"}
        )
        assert "complete" in worker.downstream_task_ids
        if name != "elexon_query":
            assert worker.retries == 2
