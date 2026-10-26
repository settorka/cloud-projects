# AWS recovery, queues and rollback

Owner: project operator. Scope: the single-host V2 development system. RPO target 24 hours; restore target 2 hours, both pending an AWS rehearsal. Host loss affects all APIs and PostgreSQL together.

## Queue recovery

Distinguish the consumer DLQs (`...-trading-input-dlq`, `...-valuation-input-dlq`) from the EventBridge routing DLQ (`...-routing-dlq`). Routing failures may indicate a broken queue policy/target, not a malformed domain event. Fix permissions/rules before replay. Routing-DLQ bodies can contain AWS wrappers; never feed them blindly into consumer redrive commands.

From `/opt/renewables/deploy/aws`, inspect consumer DLQ metadata without printing payloads:

```sh
docker compose --env-file ../../v2.env exec -T trading python manage.py queue inspect renewables-v2-dev-trading-input-dlq
```

After diagnosing and fixing the cause, redrive at most 10 validated consumer envelopes first:

```sh
docker compose --env-file ../../v2.env exec -T trading python manage.py queue redrive renewables-v2-dev-trading-input-dlq renewables-v2-dev-trading-input --max-messages 10
```

Observe acknowledgement, duplicate outcomes, queue age and positions. For routing failures, prefer replay from the retained source outbox after repairing EventBridge. Use logical destination `trading-input` / `valuation-input`, a precise UTC `--since`, `--limit 10` and `--confirm`. This may redeliver successfully handled events too; inbox records must remain. No automatic DLQ replay or blind purge.

## Database backup and restore

The root daily timer writes a full custom-format PostgreSQL dump to S3, refuses >1 GiB uploads, then emits BackupSucceeded. Seven-day expiry is configured. A DB dump is consistent; a filesystem snapshot alone is not the documented database backup method. Backup upload credentials cannot download/delete backups; use an operator role for restoration.

1. Stop APIs, workers and external ingestion. Record image SHA, schema migrations and latest successful backup timestamp.
2. Download the chosen dump using the operator's credentials to a protected machine/host. Check its object size and `pg_restore --list` before use.
3. Rehearse into a separate Compose project: `docker compose -p renewables-v2-restore --env-file ../../v2.env up -d postgres`. This creates a separate volume and initializes the three roles from the environment. Do not start Caddy or app workers in the rehearsal project.
4. Pipe the dump into that project's `postgres` container using `pg_restore -U postgres -d renewables --clean --if-exists --exit-on-error`. Never target the live project by accident.
5. Check table counts, migration history, role isolation, inbox/outbox/audit and position reconciliation. Record elapsed time and backup age. Delete only the explicitly named rehearsal project/volume afterward.
6. For actual recovery, provision a replacement host, install the exact image/config and restore into its isolated database before switching DNS or opening writes. Run migrations only when compatible with the backup version.
7. Queues can contain deliveries newer than the backup. Inspect/reconcile retained events and source revisions before reopening trading; a 24-hour DB backup cannot by itself recover acknowledged trades booked since that backup.

## Deployment rollback / teardown

Record the previous image SHA before deployment. Stop API/worker processes, restore the prior SHA and redeploy only if migrations are backward-compatible; otherwise repair forward or restore a reviewed backup. Image rollback is not a database rollback.

For cost teardown: stop accepting writes, make and verify a downloadable backup, disable host timers, deactivate and delete runtime access keys after backup verification. Backup/state buckets have `prevent_destroy`: a full destroy plan is intentionally blocked. To stop the main cost while retaining recovery data, review a targeted host teardown plan from the V2 root:

```sh
uv run --project services/trading python tools/terraform.py dev plan -destroy -target=aws_lightsail_instance_public_ports.host -target=aws_lightsail_static_ip_attachment.host -target=aws_lightsail_static_ip.host -target=aws_lightsail_instance.host -out=host-teardown.tfplan
uv run --project services/trading python tools/terraform.py dev apply host-teardown.tfplan
```

Confirm the plan removes the host, its attachment and static IP; it must not remove backups or state. Targeting is a deliberate teardown exception, not the normal deployment method. For complete cleanup, first move retained buckets into a separately managed retention stack using reviewed state operations, then remove remaining resources. ECR repositories refuse deletion while images remain: retain recovery images before removing them. Disable expected host alarms during planned absence. Lightsail stopping alone does not stop instance charges. Inspect all remaining resources and the account bill after teardown.
