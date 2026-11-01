# Elexon ETL

One Python pipeline, one Azure Container Apps Job, Blob Storage and local DuckDB.
This is an independent project; existing repo applications are unchanged.

**Cloud retirement:** the acceptance deployment was torn down at the user's
request. The local pipeline and measured evidence remain available. See
[teardown.md](teardown.md) for scope, backups and redeployment requirements.

```text
Elexon public archive → Python container → Blob raw JSON
                               │          Blob curated Parquet
                               │          Blob metadata / attempt history
                               └────────→ Log Analytics → email alerts
                                                 │
Published Parquet → local DuckDB                  └→ monitoring.kql
```

Terraform has two roots: `bootstrap` owns the subscription budget and protected
state storage; `dev` owns the application. Deployment status and measured evidence
are in [verification.md](verification.md). Do not equate Terraform validation with
a completed Azure deployment.

## Local commands

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/). Run from this directory:

```sh
uv sync --frozen --python 3.13
# Both datasets, one date. Reuse an intact completed publication when code is unchanged.
uv run --frozen elexon-etl run --date 2025-01-01
# At most seven inclusive dates; serial execution stops at the first failure.
uv run --frozen elexon-etl run --start-date 2025-01-01 --end-date 2025-01-07
# Rediscover source revisions and rebuild, reusing checksum-verified raw files.
uv run --frozen elexon-etl run --dataset PN --date 2025-01-01 --refresh
# Refresh yesterday and the preceding two UTC dates, both datasets.
uv run --frozen elexon-etl daily --lookback-days 3
# Query only the current published generation of every requested date/dataset.
uv run --frozen elexon-etl query --start-date 2025-01-01 --end-date 2025-01-07 --sql sql/coverage.sql
uv run --frozen elexon-etl query --date 2025-01-01 --sql sql/units.sql
uv run --frozen elexon-etl query --dataset BOD --date 2025-01-01 --sql sql/bid_offer_ranges.sql
```

`--dataset` is PN, BOD or BOTH (default). `--root` selects local storage, default
ignored `data/`. A single date defaults to yesterday. Query ranges allow 366 days;
processing/cleanup ranges allow seven. Missing query partitions or checksum
failures stop the query instead of silently omitting data. DuckDB uses a 512 MB
memory limit and can spill to local temporary disk.

For Azure storage, append `--storage azure --account ACCOUNT` after logging in
with Azure CLI. The job uses managed identity; no storage keys are used. Azure
queries download selected published partitions to temporary local files, capped at
512 MiB per invocation; narrow the range if larger. Local queries verify and read
files in place. Azure-to-Mac downloads may incur egress charges.

## What the data means

- Scope is **PN physical notifications and BOD bid/offer snapshots** from the public
  IRIS archive. Other datasets need separate discovery/schema contracts.
- Partitions are **UTC archive-filename dates**, not settlement days. Snapshot rows
  can refer to different settlement dates/intervals.
- Repeated source snapshots/revisions are intentionally preserved. These are not
  a final deduplicated market curve, settlement results or executable prices.
  Do not sum MW levels across snapshots as though they were independent energy.
- Each record ID hashes source filename, raw checksum and source row number. Same
  inputs produce stable IDs; equivalent observations in separate snapshots remain
  separate. Increment `TRANSFORM_VERSION` when changing transformation semantics.
- National Grid unit ID is required; an unmapped Elexon `bmUnit` remains null and
  is counted. Numeric values must be finite, timestamps timezone-aware, GB
  settlement periods 1–50 and intervals nonnegative. Negative prices/levels are
  allowed. Unknown/missing fields fail the versioned schema check.
- Publication-slot coverage reports expected/observed half-hourly **filename** slots
  and missing slots. This is diagnostic, not an upstream completeness guarantee.
  All discovered inputs must validate before publication. A gap emits a warning;
  malformed files fail the new publication and remain available as raw evidence.

## Recovery and audit records

Each dataset/date has:

```text
metadata/dataset=PN/date=YYYY-MM-DD/
  attempt.json                 latest checkpoint
  attempts/<run-id>.json        retained checkpoint/final record for each attempt
  complete.json                last successful publication pointer
raw/dataset=PN/date=YYYY-MM-DD/<source-name-hash>/<content-sha256>.json
curated/dataset=PN/date=YYYY-MM-DD/<run-id>/part-00000.parquet
```

Raw upload and checkpoint precede transformation. On failure, rerun the same bounded
range: completed partitions are verified/skipped, interrupted partitions resume
from raw files. A fresh code hash causes reprocessing. Use `--refresh` to check for
upstream revisions even when an existing output is intact. Failed attempts do not
replace the last good publication. A hard kill can leave a retained running record;
it does not make an output complete.

Manifests include source references/revisions, SHA-256 checksums, row/file/byte counts,
null-mapping counts, filename coverage, wall time, process-lifetime peak RSS,
transformation version, application-code hash and deployed image digest. This is
an application audit trail, not tamper-proof compliance storage or Blob-access
logging. No full read/write/delete access audit export is configured.

Local writes use atomic rename and a partition `flock`. Azure leases the publication
blob itself for 60 seconds, renews it and requires the lease when publishing.
A stale owner cannot replace the pointer. After killing an Azure job, wait for
lease expiry before retrying; do not break a live lease.

Daily operation refreshes the last three dates (configurable 1–7), both datasets,
serially. That catches recent source changes and short gaps. Outages or revisions
outside the window require an explicit backfill. There is no unlimited scheduler,
queue, metadata database or automatic annual job.

## Bounds and retention

| Control | Value |
|---|---:|
| Concurrent files / partitions per execution | 1 / 1 |
| HTTP attempts | 3, with 1s/2s backoff for network errors, 429 and 5xx |
| HTTP timeout | 10s connect, 60s read/write/pool |
| File / parsed record bound | 16 MiB / 100,000 rows |
| Partition listing bound | 1,000 files / 512 MiB; 10 pages |
| Listing response bound | 4 MiB checked after receipt |
| Azure allocation / execution timeout | 1 vCPU, 2 GiB / 30 minutes |
| Platform retries | 0; explicit resumable rerun |

The archive CDN omits ETags on compressed responses, so downloads request identity
encoding and verify response ETag/size against discovery. Files stream to disk,
then parse individually within the bound. Parquet row groups are written per file;
a whole year is never accumulated in Python memory.

Separate manual executions can overlap. Keep normal backfills serial; partition
leases prevent two writers for the same date/dataset, not all dates globally.

Raw revisions and per-attempt records are retained until deliberate retirement.
Old curated generations can be cleaned after seven days; the current published
output and current attempt output are always protected. Cleanup holds the partition
lock and defaults to a dry run:

```sh
uv run --frozen elexon-etl cleanup --date 2025-01-01
# Inspect the candidate list before enabling deletion:
uv run --frozen elexon-etl cleanup --date 2025-01-01 --apply
```

Cleanup does not delete raw files, audit records or Terraform state. Old audit
records may reference a retired derived output; raw inputs and code/image identity
remain the reproduction evidence. Raw/audit growth and soft-deleted copies still
need periodic operator review.

## Tests and container

```sh
uv run --frozen pytest -q
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
uv build
terraform fmt -check -recursive infrastructure
docker buildx build --platform linux/amd64 --load -t elexon-etl:pilot .
docker run --rm --platform linux/amd64 --entrypoint python \
  -v "$PWD/tests:/fixtures:ro" elexon-etl:pilot /fixtures/container_smoke.py
```

The offline image test checks both datasets, real Parquet/DuckDB and cache reuse.
`.github/workflows/elexon-etl.yml` runs tests, packaging, Terraform validation and
this image test. It neither deploys nor needs Azure secrets. A hosted CI run happens
only after pushing the workflow to GitHub.

## Deploy with Terraform

The deployer needs resource creation and RBAC assignment rights. Confirm the
subscription/region/quota and billing currency before applying. The budget amount
is 50 **billing-currency units** (£50 only for GBP). Saved plans and real tfvars are
ignored by Git; retain bootstrap state securely outside Git.

Register required providers once (registration itself does not create compute):

```sh
for provider in Microsoft.Consumption Microsoft.Storage Microsoft.App Microsoft.ContainerRegistry Microsoft.ManagedIdentity Microsoft.OperationalInsights Microsoft.Insights Microsoft.ResourceHealth Microsoft.AlertsManagement; do
  az provider register --namespace "$provider"
done
```

Wait until registration completes before applying. Terraform automatic registration
is disabled to avoid registering unrelated providers. RBAC propagation can take
minutes after deployment; retry transient authorization failures after propagation.

**Bootstrap:** copy `infrastructure/bootstrap/bootstrap.example.tfvars` to
`bootstrap.tfvars` in that directory and supply real values/current month.

```sh
terraform -chdir=infrastructure/bootstrap init
terraform -chdir=infrastructure/bootstrap plan -var-file=bootstrap.tfvars -out=bootstrap.tfplan
terraform -chdir=infrastructure/bootstrap apply bootstrap.tfplan
```

The subscription budget is created before state storage; if Azure rejects the
budget, chargeable bootstrap resources are blocked. Alerts are at £25/£40/£50
with GBP billing. Budget APIs can require billing-account readiness. State storage
has versioning/soft delete and destruction safeguards. Bootstrap initially retains
local state: keep a secure backup. Never commit it.

Back it up to the private, versioned state container after a successful apply:

```sh
export STATE_ACCOUNT="$(terraform -chdir=infrastructure/bootstrap output -raw storage_account_name)"
az storage blob upload --account-name "$STATE_ACCOUNT" --container-name tfstate \
  --name elexon/bootstrap-backup.tfstate --file infrastructure/bootstrap/terraform.tfstate \
  --auth-mode login --overwrite --no-progress --output none
```

**Application:** copy `development.example.tfvars` to `development.tfvars`, fill
unique names, subscription/operator identity and alert email. Keep image/schedule
null. Initialize the remote backend, then import the existing resource group:

```sh
export ARM_SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
export STATE_ACCOUNT="YOUR_STATE_ACCOUNT"
terraform -chdir=infrastructure/dev init \
  -backend-config="storage_account_name=$STATE_ACCOUNT" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=elexon/dev.tfstate" \
  -backend-config="use_azuread_auth=true" -backend-config="use_cli=true"
terraform -chdir=infrastructure/dev import -var-file=development.tfvars \
  azurerm_resource_group.project \
  "/subscriptions/$ARM_SUBSCRIPTION_ID/resourceGroups/rg-elexon-etl-dev"
terraform -chdir=infrastructure/dev plan -var-file=development.tfvars -out=development.tfplan
terraform -chdir=infrastructure/dev apply development.tfplan
```

Build/push after the registry exists. Match Azure's Linux architecture on a Mac:

```sh
export REGISTRY="$(terraform -chdir=infrastructure/dev output -raw registry_name)"
export LOGIN_SERVER="$(terraform -chdir=infrastructure/dev output -raw registry_login_server)"
az acr login --name "$REGISTRY"
docker buildx build --platform linux/amd64 --push -t "$LOGIN_SERVER/elexon-etl:pilot" .
az acr repository show --name "$REGISTRY" --image elexon-etl:pilot --query digest -o tsv
```

Set the returned `image_digest` in tfvars. Review/apply another saved plan to create
one manual Job with a pinned digest, BOTH datasets and explicit pilot date.

```sh
az containerapp job start --name job-elexon-etl-dev --resource-group rg-elexon-etl-dev
az containerapp job execution list --name job-elexon-etl-dev \
  --resource-group rg-elexon-etl-dev --output table
```

Check published manifests and query them with `--storage azure`. Verify a stopped
execution can resume and test notifications before scheduling. When accepted, set
`source_date=null`, `dataset="BOTH"`, `schedule_cron="0 3 * * *"` and
`lookback_days=3`. The single daily job refreshes both datasets at 03:00 UTC.
Only one daily UTC schedule is supported, matching the 27-hour freshness rule.
Changing trigger type may replace the Job; data is stored independently.

## Monitoring, alerts and operator actions

- Every partition emits structured start/success/failure/skip events with a run ID.
  The command emits success only after every requested partition completes.
- Log Analytics retains logs for 30 days with a 0.1 GB/day **soft** quota.
- One email action group and two Azure Monitor log alert rules are provisioned when
  a Job exists. Failure/coverage warnings evaluate every five minutes over 30 minutes.
  Missing daily success evaluates hourly against a 27-hour window and is enabled
  only when the daily schedule is configured.
- Rules count matching table rows directly. Failure events return alert rows;
  the freshness query returns one row only when no full daily success is present.
- Azure Monitor requires a new email receiver to be verified by an OTP entered in
  Azure Portal, within 30 minutes of saving (resend there if expired). An enabled
  receiver entry alone does not prove delivery. Complete recipient verification
  and a test notification before enabling the daily schedule.
- Startup, hard-kill or image-pull failures may emit no application event; the
  missing-success alert catches these for scheduled operation. Check execution
  status directly for manual pilots. Logging outages can also trigger freshness
  alerts. Rule deployment skips query validation before tables exist: testing real
  log queries/notification delivery is a mandatory Azure acceptance gate.
- `monitoring.kql` is a ready-to-run operational view in Log Analytics. No separate
  dashboard service is required. Platform job CPU/memory metrics remain available
  in Azure Monitor; this project does not provision Prometheus/App Insights.
- Failures: inspect execution status and `attempt.json`, fix the cause, rerun the
  same date/range. Schema drift must be reviewed; do not silently discard fields.
- Gaps: inspect filename coverage/source availability and explicitly refresh the
  dates. Never claim 48 filename slots prove complete market observations.
- At £40: pause further backfills and inspect costs. Budget alerts are delayed and
  do not stop resources. Daily freshness alerts intentionally warn if scheduling
  is left configured but successful runs stop.

Keep the £50/month constraint, but measure actual compute, logs, storage operations,
retained revisions, registry and local download egress after a representative week.
A three-day daily refresh processes six partitions/day, not just two. Query alert
rules also add a small recurring cost: confirm account pricing before enabling.

Monthly maintenance: review posted costs, raw/audit growth and old registry images.
Update locked dependencies and the pinned base image deliberately, then run CI and
a bounded Azure pilot before deploying the new digest.

To pause, remove the schedule or set `image_digest=null` (removes the Job and health
rules). Stop existing executions separately. Registry/storage still incur charges.
For retirement: export required data/audits, deliberately remove data destruction
safeguards, review a destroy plan and retire state storage last. Never delete other
projects' resource groups.

## Attribution

[Archive contract](https://github.com/elexon-data/insights-docs/blob/main/docs/iris_archive.md)
and [BMRS licence](https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/).
Keep attribution on exports and review applicable third-party rights before
redistribution. No Elexon endorsement is implied. Test fixtures use synthetic names
and values shaped like actual source responses.

Contains BMRS data © Elexon Limited copyright and database right 2026.
