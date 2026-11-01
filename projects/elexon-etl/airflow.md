# Airflow orchestration

Airflow 3.3.2 is an optional, locked Python 3.13 dependency. The original CLI
commands and lightweight container remain available without installing it.
`src/elexon_etl/workflows.py` owns plan validation and the reusable task bodies;
`dags/elexon.py` defines Airflow scheduling, mapping, retries and dependencies.
There are no shell wrappers or parallel copies of transformation logic.

## Run locally

From `projects/elexon-etl`, with Python 3.13 and uv:

```sh
uv sync --frozen --extra airflow
export AIRFLOW_HOME="$PWD/data/airflow"
export AIRFLOW__CORE__DAGS_FOLDER="$PWD/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES=False
export AIRFLOW__API__HOST=127.0.0.1
export ELEXON_STORAGE=local
export ELEXON_ROOT="$PWD/data"
uv run --frozen --extra airflow airflow standalone
```

Use the local UI at `http://127.0.0.1:8080`; standalone prints its development
login instructions. This starts local scheduler/API/DAG-processing components and
initializes a local metadata database. It is a development setup, not a hosted
service or production authentication configuration. Runtime files stay under the
Git-ignored `data/` directory. Stop the foreground process with Ctrl-C.

All four DAGs start **paused**. To use a manual DAG, unpause it and trigger it with
parameters in the UI (or the commands below). Unpause `elexon_daily` only when you
want scheduled ingestion. `catchup=False` avoids an automatic historical flood.
Ordinary CLI commands still use `uv run --frozen elexon-etl ...`; add
`--extra airflow` to uv commands when retaining the Airflow extra in the same venv.

| DAG | Schedule | Parameters | Work |
|---|---|---|---|
| `elexon_daily` | 03:00 UTC, initially paused | `dataset`, `lookback_days` (1–7, default 3) | Refresh yesterday and the preceding lookback dates |
| `elexon_run` | Manual | `dataset`, `start_date`, `end_date`, `refresh` | Ingest at most seven inclusive completed UTC dates |
| `elexon_query` | Manual | `dataset`, `start_date`, `end_date`, `sql` | Query up to 366 dates together; print results to task logs |
| `elexon_cleanup` | Manual | `dataset`, `start_date`, `end_date`, `apply` | Up to seven dates; dry run unless `apply=true` |

`dataset` defaults to BOTH. Manual date parameters must either both be supplied
or both be null (yesterday relative to the run). Daily dates are anchored to
`data_interval_end`; manual runs fall back to their recorded run start if no
interval is provided. Retries keep the same selected partitions across midnight.
Future/incomplete UTC dates and oversized ranges fail before source/storage IO.

With the standalone service running, in a second terminal using the same exports:

```sh
uv run --frozen --extra airflow airflow dags unpause elexon_run
uv run --frozen --extra airflow airflow dags trigger elexon_run \
  --conf '{"start_date":"2025-01-01","end_date":"2025-01-02","dataset":"BOTH"}'
```

For a historical backfill, trigger `elexon_run` with explicit bounded dates. Use
`refresh=true` to rediscover revisions. Avoid Airflow's unbounded historical
backfill command for this rolling-refresh DAG. Large history should be submitted
as deliberate seven-day batches after checking source coverage and storage cost.

## Task boundaries and guarantees

```text
daily / run / cleanup: plan → partitions → process[dataset/date] → complete
query:                 plan → query(all selected publications) → complete
```

The planning task creates JSON-only configuration. Each mapped task opens and
closes its own source/storage clients. Raw data, Parquet and per-attempt manifests
stay in the selected store; XCom holds only bounded plans and small result
summaries, never source records, files or client objects. Query results are in the
task log, not XCom. SQL is operator-supplied code: restrict DAG trigger permissions
to trusted operators; DuckDB is not a SQL sandbox.

Publication remains one leased dataset/date transaction: discover, cache raw,
validate, transform and atomically publish. This preserves interruption recovery
and the previous good publication. Partition tasks retry twice at two-minute
intervals and time out after 30 minutes. Plan/query/complete tasks do not retry.
Each DAG allows one active run and one active task; a run times out after two
hours. CLI execution remains serial and stops at the first error. Airflow can
continue other mapped partitions after one fails; the DAG cannot report success
unless all required tasks succeed. Clearing a failed task retries its frozen
partition, reusing verified raw data. Daily refresh deliberately rediscovers input.

Locks still protect partitions across DAGs and CLI processes. Different DAGs may
run concurrently; a competing writer fails and can retry rather than publishing
over an active writer. Do not rely on Airflow for exactly-once delivery. Success
events are downstream of processing and query work; failed DAGs emit a failure
callback in addition to task/partition errors.

Cleanup defaults to dry run, retains raw/audit/current publication and only deletes
eligible unpublished Parquet older than seven days. Query verifies all selected
publications, preserving the 512 MiB Azure download and DuckDB memory limits.

## Storage, Azure and monitoring

For local storage, every task must see the same absolute `ELEXON_ROOT`. The local
development setup uses one host. Distributed workers require shared storage or
`ELEXON_STORAGE=azure` and `AZURE_STORAGE_ACCOUNT` on every worker. Azure auth uses
DefaultAzureCredential and optional `AZURE_CLIENT_ID`; the worker identity needs
the existing scoped Blob permissions. No credential values go into DAG params.

Existing Terraform defines a **CLI Container Apps Job**, not Airflow services or
its metadata database. Those Azure resources were retired after acceptance.
This change creates no resources and makes no cloud Airflow availability claim.
If migrating scheduling to hosted Airflow, first disable the old job's cron and
stop its active executions, then validate a bounded manual DAG run before enabling
the daily DAG. Avoid running both schedulers for the same workload.

Airflow local task logs are separate from the old Container Apps Log Analytics
table. Use the Airflow UI to inspect failures/retries locally. The existing Azure
email alerts and 27-hour freshness query do not automatically monitor Airflow;
hosted operation needs an explicit log/alert integration before claiming coverage.
Expect scheduler/database overhead beyond the former £5–10/month CLI-job estimate.

## Verification

```sh
uv run --frozen --extra airflow ruff check src tests dags
uv run --frozen --extra airflow pytest -q
uv run --frozen --extra airflow python tests/airflow_smoke.py
```

The smoke script creates and removes a temporary SQLite metadata database under
`data/`, seeds synthetic PN/BOD publications, and runs real `dag.test()` executions
for mapped cache replay, daily refresh, query, dry-run/applied cleanup and invalid
backfill failure propagation. The source adapter is patched to a fixture archive
for daily refresh; no Elexon/Azure network access is needed. It is not a scheduler
soak test or a cloud deployment test. CI also checks the lightweight CLI install
separately and runs the Airflow suite with the optional dependency installed.

References: [Airflow public SDK](https://airflow.apache.org/docs/apache-airflow/stable/public-airflow-interface.html),
[dynamic task mapping](https://airflow.apache.org/docs/apache-airflow/stable/authoring-and-scheduling/dynamic-task-mapping.html),
[real DAG tests](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/debug.html).
