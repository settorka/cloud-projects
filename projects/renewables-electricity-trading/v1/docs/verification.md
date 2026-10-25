# V1 verification evidence

Verified locally on 25 October 2026, using Docker Desktop engine 28.5.2 on Apple Silicon. Linux images use Python 3.11.17, Django 5.2.18, PostgreSQL 17.7 and ElasticMQ 1.6.12. Python/uv image manifests are digest-pinned and dependencies are locked with uv 0.13.5. Each service has an independent host uv environment (the pre-existing host interpreter was 3.11.14; container tests use 3.11.17).

## Completed checks

- Three application images and three test images built successfully; Compose reached readiness and initialization jobs exited successfully.
- A separate empty PostgreSQL volume initialized all three service schemas/roles. The disposable check stack was removed afterward.
- **41 PostgreSQL-backed pytest tests passed:** Trading 22, Market Data 10, Valuation 9. Includes independent-connection races for bookings, duplicate requests and amendments, plus a crash-after-commit/before-acknowledgement test.
- Ruff lint/format and canonical event-schema copy checks passed. All service models match their committed migrations (`makemigrations --check --dry-run`).
- Full HTTP/broker acceptance passed against the final images: booking, retry, duplicate event delivery, valuation, stopped-worker catch-up, forecast breach, covering purchase, reconciliation, permissions and cross-schema access denial.
- Disposable queue probe verified visibility leases, redelivery and dead-letter routing.
- A real Elexon wind import returned HTTP 200 and stored **24 source records** separately from private synthetic inputs. Other live dataset endpoints have not been individually verified against the provider.
- A backup restored into an independent rehearsal database matched selected table counts and reconciled all four then-existing portfolios. Duration **10.45 seconds**; this is not a production RTO. The rehearsal database was removed afterward.
- Demo positions reconciled with **zero mismatches** after the baseline and burst experiments.

## Measured workload

Trading API allocation: one Gunicorn process/four threads, 0.5 CPU and 384 MiB. Worker processes have the same resource caps. PostgreSQL: 1 CPU and 768 MiB. These are short tests on a shared laptop/Docker environment, not isolated benchmark hardware or AWS measurements.

### Baseline: 100 intended requests at 10/s

Maximum 10 in flight; seed 1; duplicate every tenth request.

```json
{
  "run_id": "35d83a27-7a29-4215-b8b1-5ce199ee6db5",
  "seed": 1,
  "intended_requests": 100,
  "target_rate": 10.0,
  "sent_requests": 100,
  "generator_shed": 0,
  "elapsed_seconds": 9.927326000000903,
  "completed_requests_per_second": 10.073206017410016,
  "outcomes": {
    "201": 100,
    "idempotent_replay": 9
  },
  "latency_seconds": {
    "p50": 0.02086425000015879,
    "p95": 0.05722441699981573,
    "p99": 0.06421358299849089
  },
  "max_generator_schedule_lag_seconds": 0.001243915998202283,
  "note": "201 counts include idempotent replays; distinguish them. Verify final positions with reconcile."
}
```

91 unique accepted bookings and 9 idempotent replays. No generator shedding or HTTP errors. One short run does not demonstrate a long-term SLO.

### Stress input: 1,000 intended requests at 1,000/s

Maximum 100 in flight; one portfolio and interval.

```json
{
  "seed": 1,
  "intended_requests": 1000,
  "target_rate": 1000.0,
  "sent_requests": 140,
  "generator_shed": 860,
  "elapsed_seconds": 2.9907339999990654,
  "completed_requests_per_second": 46.81125101732342,
  "outcomes": {
    "201": 140
  },
  "latency_seconds": {
    "p50": 1.6025787920007133,
    "p95": 2.1046589159996074,
    "p99": 2.1581950830004644
  },
  "max_generator_schedule_lag_seconds": 0.02944391599885421,
  "note": "201 counts include idempotent replays; distinguish them. Verify final positions with reconcile."
}
```

**Only 140 requests reached the API; the bounded generator shed 860.** All 140 received accepted responses. This does not demonstrate 1,000/s service capacity, and 46.8 completions/s is not an established maximum. The generator correctly exits nonzero on shedding. Future runs should select the workload envelope and hardware explicitly, record sent/admitted/completed work separately and verify financial state.

## Remaining limitations

- Local loopback HTTP and known seeded tokens are not a production security configuration.
- Shared PostgreSQL, no high availability or regional failover.
- ElasticMQ is ephemeral in this configuration. Worker restart recovery is verified; broker loss requires retained-outbox replay. AWS durability, IAM, EventBridge and actual SQS parity are V2 work.
- API-process metrics do not aggregate worker-process counters automatically. Persisted outbox/job status is available.
- Simplified fixed-price marks are not official settlement, full generation economics, credit risk or audited business profit.
- No CloudWatch alarms, SNS notification delivery, cloud cost enforcement or Terraform deployment in V1.
- A GitHub Actions workflow is supplied; no remote CI execution is claimed.
- No AWS resources, commits or pushes were created.
