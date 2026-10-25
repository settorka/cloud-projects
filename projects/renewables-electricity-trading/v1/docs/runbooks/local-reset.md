# Stop, restart and destructive reset

Use `make down` to stop/remove project containers and retain the PostgreSQL volume. Use `make up` to resume. ElasticMQ is in-memory locally: recreating it loses queued messages, including DLQs. Already-published outbox rows do not automatically republish. A non-destructive environment stop is therefore not a durable-broker guarantee; reconcile and republish retained source snapshots if queues were lost. Actual SQS durability is verified in V2.

Restart only a worker with `docker compose --env-file .env restart trading-worker`. Recreating the broker is a different operation.

For a completely disposable reset, first back up anything needed. **`docker compose --env-file .env down --volumes` permanently deletes this project's local database volume.** Run it only when intentionally discarding all trades/history. Then `make up` and `make demo`.

Verification: check seeded identities, schema ownership, fresh demo inputs and `make e2e`. If credentials no longer work, verify `.env` matches initialization before resetting.
