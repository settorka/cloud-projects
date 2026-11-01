# FX settlement analytics

Real ECB reference observations, with SQL Server and SSIS on Azure Windows. Settlement
trades/payments are explicitly synthetic. The dimensional warehouse and reconciliation
are working. SSAS Tabular and the read-only Streamlit dashboard are deployed and verified on the Windows VM.

## Working implementation

- Original ECB archive and manifest preserved in private Azure Blob Storage.
- Checksum-verified download on the VM using its managed identity, without storage keys.
- Date-filtered preparation of observed EUR/USD and EUR/GBP, plus derived GBP/USD.
- Actual saved SSIS package executes `warehouse.LoadRates` using a SQL file connection.
- SQL validates inputs, records rejections, publishes valid batches atomically and refuses
  conflicting replays. Identical replay records a successful run with zero new inserts.
- Reproducible synthetic trades/payments, loaded by a second actual SSIS package.
- Set-based, as-of reconciliation with split/partial allocations and exception views.
- Dense date, currency and counterparty dimensions; trade/payment/expected-leg facts.
- Prepared CSVs, batch manifests and execution reports are stored in Blob. Reports link
  run ID, code fingerprint, SSIS execution GUID and package/prepared-file checksums.

Verified: 765 rates for 2025, followed by a successful replay with zero inserts and 765
published rows. A deliberately invalid batch failed through the actual SSIS package,
recorded rejections and published no partial data. Its test audit rows were removed.
The initial pre-instrumentation load lacks an SSIS execution GUID; later runs capture it.
Original row lineage is retained rather than rewritten to pretend the replay was the load.

## Source constraints

[ECB reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html)
are informational rates normally published around 16:00 CET on working days except
TARGET closing days; ECB discourages transaction use. They contain no actual trades,
payments, spreads or intraday prices. Missing observations are never forward-filled.

GBP/USD = USD-per-EUR / GBP-per-EUR using the same date and physical source row.
SQL independently checks both inputs and the cross calculation. Preparation uses decimal
arithmetic; the warehouse stores decimal(28,14), with an explicit rounding tolerance in
cross-rate validation. The selected 2025 prepared CSV is about 90 KB: this is not evidence
of high-volume performance. The original historical archive is about 642 KB.

## Current warehouse and lineage

| Entity | Grain |
|---|---|
| audit.SourceFile | Immutable source archive checksum |
| audit.PipelineRun | One attempted warehouse batch |
| audit.RateReject | One rejected input row in a run |
| warehouse.DimCurrencyPair | Ordered base/quote pair |
| warehouse.FactFxRate | Rate date, pair and source snapshot |

Each rate retains its source hash, physical row, contributing columns and original load
run. The published view exposes only successful runs. Different source snapshots remain
separate: consumers must select a snapshot to avoid counting repeated observations across
downloads. Replay `rows_loaded` counts validated input rows; `rows_inserted` counts new facts.

Settlement model:

| Entity | Grain |
|---|---|
| DimDate / DimCurrency / DimCounterparty | Calendar date / currency / synthetic counterparty |
| audit.SettlementBatch | Immutable synthetic manifest hash |
| FactTrade | Trade within one synthetic batch |
| FactSettlementLeg | Expected base/quote currency movement for a trade |
| FactPayment | Payment record within a synthetic batch |
| BridgeSettlementAllocation | One payment-to-leg allocation |

The bridge primary key prevents allocating one payment to multiple legs. Composite
foreign keys bind fact lineage to the source recorded by its load run. Currency-pair,
rate-date and source-snapshot foreign keys link each trade to its ECB observation.
The date dimension is continuous across full calendar years, including older batches.

Reconciliation orders eligible payments by date then identifier and uses a windowed
cumulative amount to cap allocations at the expected leg amount. Publication is transactional;
re-running reconciliation replaces allocations atomically. All queries must select a batch:
1,000- and 10,000-trade demonstrations intentionally coexist and reuse scoped trade IDs.

Synthetic scenarios cover exact, split, partial, missing, duplicate-candidate, wrong-currency,
late and overpaid base legs; quote legs are exact controls. Hand-calculated SQL fixtures also
cover wrong direction, unknown references and future payments. Duplicate candidates are a
heuristic, not proof of duplicate bank activity. Source payment identifiers must be unique.

Amounts are gross positive movements with a separate pay/receive direction. Never add
currency totals together or label gross outstanding amounts as net exposure. The demo uses
two weekdays to settle, two decimal places and half-up rounding, without holiday calendars,
spreads, netting or payment-versus-payment. As-of dates are simulated dates from the manifest;
future payments are excluded and an unpaid leg becomes overdue after its due date.

### Measured development workload

| Trades | Payments | Expected legs verified | SQL reconciliation |
|---|---:|---:|---:|
| 1,000 | 2,125 | 2,000 | 109 ms |
| 10,000 | 21,250 | 20,000 | 609 ms |

Single observed runs on the existing 4-vCPU/16-GB VM, not an SLO or a controlled comparison.
Timings come from SQL audit start/finish timestamps and exclude generation, transfers and
verification. The first 10,000-trade SSIS load took about 6.14 seconds. All leg allocations,
outstanding amounts and late flags matched pre-generated expectations; replay inserts no
source duplicates. Windowed duplicate checks and indexed staging/reference lookups avoid
per-row database calls. The actual 1,000- and 10,000-trade inputs and package evidence are
preserved in Blob, with checksums independently verified.

## Local development

```sh
uv sync --group dev
uv run python -m pipeline.download_ecb --output data/ecb
uv run python -m pipeline.prepare_rates data/ecb/eurofxref-hist.zip \
  --start 2025-01-01 --end 2025-12-31 --output data/prepared/fx_rates.csv
uv run pytest
```

Export `.env.example` settings (not automatically loaded), authenticate with `az login`,
then add `--upload` to the download command. Container must exist and the identity requires
Storage Blob Data Contributor. Replays verify existing bytes and preserve the committed
manifest. Partial raw uploads recover by publishing the missing manifest.

## Azure infrastructure and operation

Existing resource group `rg-fx-warehouse-dev`, UK South, is referenced rather than managed.
Terraform provisions storage `stfx36c63c6a50e8`, private container `fx-data`, network, VM,
managed identity and persistent disk. Shared-key authentication and anonymous Blob access
are disabled. Blob uses an authenticated public HTTPS endpoint, not a private endpoint.

VM `vm-fx-dev`: SQL Server 2022 Developer / Windows Server 2022, `Standard_D4ns_v6`,
4 vCPUs / 16 GB, verified compute price £0.40/hour. SQL Server, SSIS, SSAS `FXTABULAR`
(mode 2) and Python 3.12.10 run on it. Project data is on persistent disk F:.

The NSG permits SSH only from the Bastion subnet when Bastion is enabled.
An optional operator CIDR allows direct SSH when Bastion is disabled.
SQL/SSAS/Streamlit are never publicly allowed. Mac browser access through Bastion
was verified on 1 November 2026, including dashboard health and rendered metrics.
Daily deallocation is configured at 22:00 London; stop compute earlier when finished:

```sh
az vm deallocate -g rg-fx-warehouse-dev -n vm-fx-dev
```

Disks/public IP remain billable. Developer licensing is dev/test only. Local ignored
Terraform state and `local.auto.tfvars.json` contain sensitive values; preserve them,
keep them private and never commit them. The variable file is mode 0600. Keep
`enable_windows=true` in subsequent plans unless deliberately removing compute.

`scripts/setup-windows.ps1` initializes only an empty expected-size disk and installs
Tabular from the Developer media. `scripts/setup-python.ps1` verifies the Python installer
signature. The approved one-time `bootstrap-warehouse.ps1` created the database through a
brief single-user restart. SYSTEM owns FxWarehouse, with no server-wide sysadmin role.

## Deployment and tests against Windows

From the project directory, use the small Makefile wrappers:

```sh
make deploy-sql                 # Apply warehouse/procedures before pipeline execution
make rates                      # Load/replay the real ECB snapshot
make settlements                # 1,000 synthetic trades, seed 42
make settlements COUNT=10000     # 10,000 trades; same seed and scenarios
make test
make test-sql                    # Independent, hand-calculated live SQL checks
```

`COUNT` and `SEED` are explicit parameters. Source generation is bounded at 100,000 trades;
that upper bound has not been performance-tested. `run_windows.py` transfers explicitly
listed assets and accepts safely quoted PowerShell parameters. `pipeline/common.py` shares
file-integrity/SQL-input logic; `scripts/ssis-runtime.ps1` shares managed-identity access,
package execution and reporting. One VM-wide pipeline mutex prevents the rate and settlement
flows from racing over shared local files. Package artifacts are addressed by checksum so a
later build does not overwrite the artifact referenced by an earlier run.

The script's source snapshot/date range parameters are explicit, pinned defaults for this
first reproducible load. `ssis/build-package.ps1` is the authoritative package builder;
`ssis/LoadRates.dtsx` and `ssis/LoadSettlements.dtsx` are generated, executed examples. Packages run through the installed
SSIS runtime in file deployment mode, not through SSISDB. The Execute SQL Tasks ingest
prepared JSON batches; this version does not use a visual data-flow transformation pipeline.

```sh
uv run python scripts/run_windows.py scripts/test-ssis-rejection.ps1
FX_LIVE_AZURE=1 uv run pytest tests/integration/test_blob_ingestion.py -v
```

SQL checks cover unpublished running batches, grain/provenance constraints, bad cross
rates, failed-run audit, retry, idempotency and immutable lineage. Hand-calculated settlement tests verify source replay/rejection, calendar continuity,
as-of cutoffs, partial/split allocations, late settlement, overpayments, unmatched payments
and reconciliation replay. The SSIS rejection check
restores the input file and removes its own test audit rows. Blob tests use unique fixtures
and delete only those objects. Runners require a guest success marker: Azure operation
success alone does not prove PowerShell/SQL success.

## Monitoring and remaining work

`audit.PipelineHealth` exposes rates, settlement ingestion and reconciliation runs with
status, elapsed time, received/loaded/inserted/rejected counts, rejection evidence, package
identity and errors. Expected business exceptions remain separate from ingestion failures.
Synthetic manifest records seed, generator fingerprint, file hashes, rate source and as-of
date. Trade/payment rows retain their CSV record number and original load run.

Remaining: calendar-aware freshness
and alerting, and interruption/concurrent-worker recovery tests. Preparation failures occur
before the SQL run is created; they currently surface through Windows execution errors,
not PipelineRun rows. The shared Windows VM remains a development/demo simplification.


### Temporary Mac access through Bastion

The Streamlit service listens only on the VM loopback interface. The optional
Standard Bastion uses HTTPS to carry an SSH tunnel, with the VM host key checked
against evidence retrieved from private Blob Storage. No public SQL, SSAS or
Streamlit ports are opened. Direct SSH from this Mac timed out even after the
VPN was disconnected; Bastion is the selected alternative.

Run `make connect`, then open
http://127.0.0.1:8501. Run `make disconnect` to close local tunnels.
**Run `make bastion-off` when finished** to remove the temporary Bastion host,
its public IP and subnet. This checks the Terraform plan and refuses unrelated
resource changes; the warehouse VM and data remain. Public inbound access stays
closed. Bastion costs approximately £0.23/hour extra until deleted, even when
the VM is deallocated. Do not run teardown while the provisioning apply holds
the Terraform state lock.

The deployed model has eight tables, eleven relationships and fifteen DAX
measures. Validation compared 144 filtered contexts with SQL. The dashboard
runs as LOCAL SERVICE with SQL SELECT access only on the analytics schema and
read permission on the Tabular model. Its real service identity and Streamlit
controls passed the Windows smoke test. Unverified or stale model state blocks
metrics. A full analytics projection regression and DBCC CHECKDB also passed.
These are development validation results, not production availability claims.
