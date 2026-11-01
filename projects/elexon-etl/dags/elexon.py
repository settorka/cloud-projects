"""Airflow DAGs: shared Python task bodies, no subprocess CLI wrappers.

Configure ELEXON_STORAGE, ELEXON_ROOT and AZURE_STORAGE_ACCOUNT on every worker.
Only bounded plans and small completion summaries pass through XCom.
"""

from datetime import timedelta

import pendulum
from airflow.sdk import DAG, Param, get_current_context, task


def failed_invocation(context):
    from elexon_etl.events import emit

    emit("invocation_failed", dag_id=context["dag"].dag_id, error_type="AirflowDagFailure")


def build_dag(command):
    params = {"dataset": Param("BOTH", enum=["PN", "BOD", "BOTH"])}
    if command == "daily":
        params["lookback_days"] = Param(3, type="integer", minimum=1, maximum=7)
    else:
        params.update(
            {
                "start_date": Param(None, type=["null", "string"], format="date"),
                "end_date": Param(None, type=["null", "string"], format="date"),
            }
        )
    if command == "run":
        params["refresh"] = Param(False, type="boolean")
    elif command == "cleanup":
        params["apply"] = Param(False, type="boolean", description="False only lists candidates")
    elif command == "query":
        params["sql"] = Param(
            "SELECT dataset, source_file_date, count(*) AS rows FROM elexon GROUP BY ALL ORDER BY ALL",
            type="string",
            minLength=1,
            maxLength=10000,
        )

    with DAG(
        dag_id=f"elexon_{command}",
        description=f"Elexon {command}: shared CLI pipeline with Airflow orchestration",
        schedule="0 3 * * *" if command == "daily" else None,
        start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
        catchup=False,
        is_paused_upon_creation=True,
        max_active_runs=1,
        max_active_tasks=1,
        dagrun_timeout=timedelta(hours=2),
        on_failure_callback=failed_invocation,
        params=params,
        tags=["elexon"],
    ) as dag:

        @task(retries=0)
        def plan():
            import os

            from elexon_etl.workflows import invocation_event, make_plan

            context = get_current_context()
            # Freeze the selected dates to the DagRun, never to a retry's wall clock.
            reference = context.get("data_interval_end") or context["dag_run"].start_date
            result = make_plan(
                command,
                **context["params"],
                reference=reference,
                storage=os.getenv("ELEXON_STORAGE", "local"),
                root=os.getenv("ELEXON_ROOT", "data"),
                account=os.getenv("AZURE_STORAGE_ACCOUNT"),
            )
            invocation_event("invocation_started", result)
            return result

        @task(retries=0)
        def partitions(plan):
            return plan["partitions"]

        @task(retries=2, retry_delay=timedelta(minutes=2), execution_timeout=timedelta(minutes=30))
        def process(plan, partition):
            from elexon_etl.workflows import process_partition

            return process_partition(plan, partition)

        @task(retries=0, execution_timeout=timedelta(minutes=30))
        def query(plan):
            from elexon_etl.workflows import query_publications

            return query_publications(plan)

        @task(retries=0)
        def complete(plan):
            from elexon_etl.workflows import invocation_event

            invocation_event("invocation_succeeded", plan)

        selection = plan()
        if command == "query":
            work = query(selection)
        else:
            work = process.partial(plan=selection).expand(partition=partitions(selection))
        # Default all_success: failed/upstream-failed mapped tasks cannot emit success.
        work >> complete(selection)
    return dag


daily = build_dag("daily")
backfill = build_dag("run")
query = build_dag("query")
cleanup = build_dag("cleanup")
