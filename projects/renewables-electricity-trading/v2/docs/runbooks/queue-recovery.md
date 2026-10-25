# Queue backlog, failed delivery and DLQ recovery

Symptoms: stale applied inputs, absent trade valuation, pending outbox or worker exceptions. First distinguish source publication, outbox delivery, broker backlog and consumer application.

```sh
docker compose --env-file .env logs --tail 100 market-data-worker trading-worker valuation-worker
docker compose --env-file .env exec -T trading python manage.py queue inspect trading-input
docker compose --env-file .env exec -T valuation python manage.py queue inspect valuation-input
docker compose --env-file .env exec -T trading python manage.py queue inspect trading-dlq
```

Check authenticated service `/v1/status` for pending outbox, worker heartbeat and last error. A successful loop heartbeat can coexist with a poison message. Queue counts are approximate; inspect DLQ bodies with `queue inspect <name> --sample` (temporarily changes their visibility, does not delete).

Recovery: repair code/configuration first, restart the affected worker and verify pending ages decline. For a **valid** previously failed event, redrive a bounded batch:

```sh
docker compose --env-file .env exec -T trading python manage.py queue redrive trading-dlq trading-input --max-messages 10
```

This copies the original envelope, then deletes the source message only after successful send. Duplicate delivery remains possible and is safe. Invalid envelopes are deliberately not redriven: preserve evidence and fix the producer or create an explicitly corrected event. Never purge queues to clear an alarm. DLQ clearing alone is not recovery.

Verification: verify applied revisions/positions, valuation input versions, successful reconciliation and no recurring DLQ entries. Stop/start a consumer to test catch-up. Broker recreation loses local messages because ElasticMQ is ephemeral; do not equate emulator persistence with AWS SQS.

Run `docker compose --env-file .env exec -T trading python manage.py broker_check` for a disposable broker-only visibility/redelivery/DLQ exercise. It creates unique probe queues and deletes only those queues. It does not inject poison into business queues.

## Broker recreation or lost local queue contents

Stop clients, fix the broker, and inspect the time range that could have lost messages. Republish retained committed outbox deliveries from each owning producer, with a bounded explicit window:

```sh
docker compose --env-file .env exec -T market-data python manage.py replay_outbox --destination trading-input --since 2026-10-25T00:00:00Z --limit 1000 --confirm
docker compose --env-file .env exec -T market-data python manage.py replay_outbox --destination valuation-input --since 2026-10-25T00:00:00Z --limit 1000 --confirm
docker compose --env-file .env exec -T trading python manage.py replay_outbox --destination valuation-input --since 2026-10-25T00:00:00Z --limit 1000 --confirm
```

Replace the example timestamp with the actual incident window. This changes delivery markers, never financial history. Consumers retain original event IDs and deduplicate already-applied work. Choose a limit covering the incident window; do not repeatedly reset the same first batch. If retained outbox history does not cover the loss, recover from authoritative revisions instead of pretending replay is complete. Verify revisions, financial reconciliation and queue drainage before resuming clients.
