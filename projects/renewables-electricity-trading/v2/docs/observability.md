# V2 observability

See [process states and tracing](process-lineage.md), [quantified operating bounds](aws-design.md) and the [AWS observability runbook](runbooks/aws-observability.md).

## Inherited local metrics

# Local observability

V1 emits JSON logs to container stdout, HTTP request/latency histograms, portfolio lock-wait histograms and event outcome counters. `/metrics` is authenticated. Each API uses one process/four threads, so its in-process counters are coherent; background worker counters are not automatically aggregated into API process counters. Persisted job and outbox gauges are visible across processes. Do not describe them as complete per-worker telemetry.

Inspect `GET /v1/status`, Market Data `/v1/sources`, Trading positions/breaches and Valuation runs alongside logs. `JobStatus.last_success` for a worker is a loop heartbeat, **not proof every message succeeded**. Message failures, DLQ contents and applied data freshness must be checked too. Current queue counts/age are available from the SQS API; the queue runbook contains commands. Container logs rotate at 3 × 10 MB per process locally. Financial audit records remain in PostgreSQL.

Proposed AWS rules for V2: external booking-path failure, unexpected booking errors, growing oldest outbox/queue age, any DLQ message, stale required input, position mismatch, low storage, task exits and budget thresholds. Source freshness is dataset-specific: a five-minute importer does not imply a five-minute publication cadence. A live Elexon failure does not overwrite the working synthetic scenario.

Request IDs and event IDs are log fields, never metric labels. Do not log tokens or full financial payloads. API latency labels use route templates. Financial history is not sampled; high-volume operational success logs are omitted. Position mismatches block affected portfolio writes until repair followed by a clean independent check.

Local diagnosis: `docker compose --env-file v2.env logs --tail 100 trading trading-worker market-data-worker valuation-worker`. Check `docker stats` during tests. No CloudWatch/SNS resources are provisioned by V1. Alert delivery, centralized tracing, monitoring retention and detailed database resource dashboards are later deployment work.
