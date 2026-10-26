# AWS observability and incident triage

Owner: project operator. Initial diagnostic targets: detect queue/host failures within 10 minutes, acknowledge during an attended development session within 15 minutes. No 24/7 support promise.

## Signals and thresholds

| Signal | Threshold | First action |
|---|---|---|
| Consumer/routing DLQ | Any visible message for 1 minute | Stop replay; inspect message format and failure source |
| Oldest main-queue message | >120 seconds for 2 minutes | Check worker, credentials, DB locks and outbox |
| Host health | Missing or zero for 10 minutes | Check Lightsail status, disk, Docker and database |
| Disk | >70% for 10 minutes | Stop ingestion/load tests; inspect growth and backups |
| Backup | No success for 26 hours | Inspect backup timer and S3 upload, then run manually |
| HTTP p95 / failures | Target <500 ms / <1% over controlled 5-minute run | Investigate locks, CPU credits and saturation; not an automated CloudWatch alarm yet |
| Log allowance | >20 MiB/day | Reduce noisy logging; check exporter loops and repeated errors |

CloudWatch alarms and SNS subscription are Terraform-managed; confirm the email subscription. The 5-minute host timer reports health/disk and per-service worker/outbox status. A collector outage may leave logs/traces absent while trade processing continues; telemetry is not the financial source of truth.

As root, from `/opt/renewables/deploy/aws`:

```sh
docker compose --env-file ../../v2.env ps
docker compose --env-file ../../v2.env logs --tail 100 trading-worker valuation-worker
docker compose --env-file ../../v2.env logs --tail 100 otel-collector
systemctl status renewables-check-host.timer renewables-backup.timer
journalctl -u renewables-backup.service --since '2 days ago'
```

Do not print `v2.env`, process environments or credentials. Use bounded log queries. In CloudWatch Logs Insights, select the Terraform-created group and a 15-minute window:

```text
fields @timestamp, message, trace_id, event_id, process_id, process_state, error_code
| filter event_id = 'EVENT_UUID'
| sort @timestamp asc
| limit 100
```

Use `trace_id` to open the sampled X-Ray trace. The durable lookup is `python manage.py process_history --identity EVENT_UUID --limit 20` in the relevant container. `PUBLISHED` proves bus acceptance only. `APPLIED` proves committed consumer work. `ACK_FAILED` means redelivery is expected and inbox deduplication must prevent duplicate business effects.

For local tracing, from V2 run `docker compose --env-file v2.env -f compose.yaml -f compose.otel.yaml --profile observability up -d --build`, then the E2E scenario. Inspect collector logs for booking→publish→consume spans with the same trace ID. This local profile samples 100%; AWS defaults to 1%. Do not leave diagnostic sampling enabled on AWS.
