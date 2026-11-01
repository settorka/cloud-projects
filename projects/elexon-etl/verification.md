# Verification evidence

Verified on **31 October 2026** in Azure UK South. These are historical acceptance
results; the user subsequently requested cloud retirement (see [teardown.md](teardown.md)).
The tested daily configuration was **03:00 UTC, PN and BOD, rolling three-day refresh**.
This is a development data pipeline; measured samples are not a production SLA or
an exact forecast for an annual backfill.

## Local and Azure weekly data parity

The 1–7 January 2025 filename-date partitions were processed locally and in Azure.
All **14 published Parquet checksums and row counts match exactly** across the two
environments. The Azure-backed DuckDB query across all seven dates also succeeded.

| Measurement | PN | BOD | Combined |
|---|---:|---:|---:|
| Source files | 336 | 336 | 672 |
| Source-snapshot rows | 742,177 | 1,104,427 | **1,846,604** |
| Raw bytes | 166,352,893 | 288,355,143 | **454,708,036** |
| Parquet bytes | 37,312,214 | 54,505,113 | **91,817,327** |

The initial local week's summed partition runtime was 159.632 seconds, with the
first date already cached. A subsequent seven-day rerun reused all 672 raw files
with zero source downloads and took 17.443 seconds summed across partitions.
Source CDN caching and hardware affect these timings.

Coverage diagnostics originally flagged exact-minute offsets as gaps. Inspection
found valid filenames such as `PN_202501021401_...`: publication was one minute
late. The diagnostic now groups valid timestamps into half-hour buckets, reporting
jitter separately. All 14 weekly partitions have all 48 buckets; 34 files were off
an exact half-hour boundary. This does not prove complete upstream observations.

Metadata-only PN checks on both UK clock-change dates, 30 March and 26 October 2025,
also found 48 filename buckets each. They contained 23 and 5 off-boundary filenames,
respectively; no false missing-bucket warning was produced.

## Azure execution and analysis

The first native image execution, `job-elexon-etl-dev-rtnymxd`, succeeded from
16:44:36 to 16:45:20 UTC: **44 seconds including platform startup**.

| 1 January 2025 | PN | BOD |
|---|---:|---:|
| Files | 48 | 48 |
| Rows | 106,267 | 157,231 |
| Raw bytes | 23,821,067 | 41,046,188 |
| Parquet bytes | 5,342,761 | 7,760,425 |
| Application partition runtime, seconds | 8.504 | 8.775 |
| Process-lifetime peak RSS, bytes | 111,460,352 | 118,312,960 |

Published source-code hashes match the finished local source. The deployed image is:

```text
acrelexone0a31fe7.azurecr.io/elexon-etl@sha256:369e584a2767b1b0da9c57b3d190fbbc65d3165fd9251444c3ab74ae14def718
```

A manually invoked rolling three-day command processed the recent PN/BOD dates and
succeeded in **79 seconds** (16:57:19–16:58:38 UTC). Its success caused the exact
freshness condition to clear. The final rule uses a table-row count: one row when
daily success is absent, zero when it is present.

The final Terraform trigger change replaces the idle Job. Native execution history
before replacement was saved in ignored `data/`; per-attempt Blob records and Log
Analytics remain independent of Job replacement. The final configured Job is run
again on demand as a closing acceptance check. That final configured execution,
`job-elexon-etl-dev-ex31niz`, succeeded from 17:09:42 to 17:10:50 UTC (**68 seconds**).

## Failure, recovery and publication safety

- Actual Blob checks passed with Entra authentication, publication writes under a
  renewable lease, rejection of a competing writer, and subsequent reacquisition.
  Azure's create-only upload can return `LeaseIdMissing`/412 before checking object
  existence. The adapter normalizes this to the same writer-conflict error used
  locally; an offline regression test covers it.
- A platform stop request was too slow to interrupt the short 3 January pipeline:
  its data completed before the platform marked the execution Stopped. That result
  was not counted as proof of partial-run recovery.
- A separate acceptance execution killed its **own production pipeline subprocess**
  immediately after the first 4 January PN file checkpoint. The execution failed;
  the manifest remained running with **one durable raw file and no published output**.
- After lease expiry, the normal production command resumed it successfully:
  **1 file reused, 47 downloaded, 106,112 rows published**, 8.714 application seconds.
  The old interrupted attempt record remained available alongside the new completed
  record. The temporary per-execution fault-injection command is not the scheduled
  Job configuration or an application runtime feature.
- An isolated `1900-01-01` empty-source request deliberately failed. Its structured
  failure events appeared in Log Analytics and made the deployed failure query
  return two matching failure events (partition and invocation for the same failure).

Failed/Stopped acceptance executions are expected history, not missing production
partitions. The publication manifest, file accounting and platform execution status
are checked separately.

## Monitoring and budget

Deployed: 30-day Log Analytics, the operator email action group, failure/coverage
rule (five-minute evaluation) and missing-daily-success rule (hourly, 27-hour window).
Both exact KQL queries were executed successfully against the real workspace. Final
conditions use table-row Count, avoiding unnecessary scalar metric aggregation.
The freshness query returns zero rows on current data and one row when replayed
against the period before the first daily success.
The freshness rule is enabled with the daily schedule.

The operator completed email verification. Azure's current `2026-03-01-preview`
API reports the recipient as `Verified`; a test notification finished **Complete**
with the email action **Succeeded**. The older CLI/API rejected the same receiver,
so a successful current-API result was required. This verifies Azure's send result,
not an independent inspection of the recipient's mailbox.

The final `1900-01-02` empty-source test execution failed as intended. At
**17:21:53 UTC**, Azure Alerts Management reported `elexon-failures` as **Fired**
(alert instance `880071fe-e74c-29f3-9654-d87f19d20017`). This verifies native failure
detection in addition to the successful email-route test. The alert will resolve
after its rolling failure window clears; the intentional tests remain in history.

The billing profile is active and denominated in **GBP**; the subscription reports
Pay As You Go. The acceptance subscription-wide budget was **£50/month**, with actual-cost
notifications at 50%, 80% and 100%. The budget was established before state storage.
Budget notifications are not a spending cap.

A planning allowance of £5–10/month was estimated for modest operation;
registry, alert evaluations, storage transactions, retained data, logs and egress
all contribute. The daily three-day refresh executes six partitions, not two.
Immediate Cost Management queries were unavailable during account setup and billing
data is delayed: an actual invoice/cost-total claim has not been verified. Review
posted usage after billing ingestion before launching an annual backfill.

## Build and infrastructure checks

- **32 offline tests pass**, including bounded ranges, both-dataset daily processing,
  resume/skip behavior, audit retention, source revisions, corruption detection,
  CLI failure signaling, cleanup protection, source schema and retry behavior.
- Ruff lint/format, source distribution and wheel builds pass. Packaging excludes
  local data, virtual environments and Terraform provider caches.
- Linux amd64 image build and offline PN/BOD → Parquet → DuckDB → replay smoke test
  passed. The image runs as an unprivileged user and pins its base digest.
- Terraform roots use locked AzureRM 4.81.0, with Mac/Linux provider checksums.
  Provider-backed validation passed and real plans/applies succeeded. The existing
  project resource group was imported, not recreated.
- Both deployed Terraform roots were checked with `plan -detailed-exitcode` after
  final configuration: **no changes**.
- Before retirement, bootstrap state had a private, versioned Blob backup and
  application state used the protected Azure backend. Retirement exports state
  locally before deleting cloud state storage. Real tfvars, plans, state and
  runtime data are Git-ignored.
- The scoped GitHub Actions workflow is generated and its YAML parses. Its local
  checks were executed, but a hosted run requires committing/pushing the workflow;
  no GitHub push was performed.

## Operating boundaries

Keep backfills serial and bounded to seven dates per invocation. Queries reject
missing or corrupt publications. Daily refresh covers only its 1–7-day lookback;
older gaps/revisions need an explicit backfill. Raw files and attempt history are
retained; cleanup only deletes eligible unpublished Parquet generations older than
seven days and defaults to a dry run. This is not immutable compliance auditing or
full Blob-access logging, and no production availability guarantee is asserted.

Earlier read-only 2025 archive enumeration found 17,520 PN and 17,520 BOD files,
together 24,739,411,087 stored bytes. That is not the size of all Elexon data or an
exact annual record count. Recheck coverage and costs before expanding scope.

Contains BMRS data © Elexon Limited copyright and database right 2026.
