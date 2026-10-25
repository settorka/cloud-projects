# Local database backup and restore

Backup is useful only if restoration is tested. Stop mutating clients and workers for a coordinated local snapshot; preserve broker state while inspecting or drain all outboxes/queues first. A database backup does not capture ElasticMQ memory.

```sh
mkdir -p backups
docker compose --env-file .env exec -T postgres pg_dump -U postgres -d renewables -Fc > backups/renewables.dump
```

The custom dump includes all three schemas. It contains sensitive local history; `backups/` is ignored. Runtime roles are provisioned by the database bootstrap, not by this dump.

First restore into a **new rehearsal database**, never overwrite the working database as a verification step:

```sh
docker compose --env-file .env exec -T postgres createdb -U postgres renewables_restore
docker compose --env-file .env exec -T postgres pg_restore -U postgres -d renewables_restore --exit-on-error < backups/renewables.dump
```

Inspect schema/table counts and ownership. Run Trading reconciliation against the rehearsal database:

```sh
docker compose --env-file .env run --rm --no-deps -e DB_NAME=renewables_restore trading python manage.py reconcile demo
```

Run `python tools/recovery_check.py` through the Trading uv environment for an automated disposable rehearsal with cleanup. It verifies table counts and reconciliation and drops only its unique rehearsal database afterward.

Production restoration requires coordinating committed history with inbox/outbox progress and upstream snapshots. Do not restart workers against a restored database while retaining unrelated queue state. For V1, pause processing, verify restored financial state, then deliberately republish retained authoritative snapshots if the local broker was lost. Record elapsed restore time and any gaps; no RTO/RPO claim is established by merely producing a dump.
