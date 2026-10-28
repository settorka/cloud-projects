# Operations and limits

## First checks

- `/health/live` proves only that the API process runs.
- Authenticated `/v1/status` separates data age from database reachability. It does
  not report Kafka lag or upstream completeness.
- Inspect `ingestor`, `processor`, `references`, `postgres` and `kafka` logs.
- A disconnected source may leave no new rows. Silence never proves port departure.
- PostgreSQL failures produce HTTP 503; historical data can be served while the
  source is stale, with explicit freshness labels.

## Replay and failure boundaries

Kafka processing is at least once; idempotent database writes suppress duplicates.
The consumer resumes its committed position after restart. Never reset the live
consumer group casually. A reset cannot reconstruct observations never received
and cannot restore data older than Kafka retention. Position events older than
seven days are not reintroduced into the live database. Delayed positions cannot
regress latest state or silently recompute earlier visit decisions.

Poison records are quarantined transactionally before offsets advance. Inspect and
correct the adapter before replaying a bounded set. Do not print raw quarantine
payloads into shared logs. The ingestor stops after failed Kafka publication; a
supervisor restart makes the gap visible in logs but cannot recover the lost MQTT
message. A continuously failing source can leave the service alive with stale data.

## Retention

Timescale drops detailed position chunks under a seven-day policy; this is periodic
chunk deletion, not deletion of each row exactly at its seventh-day boundary.
V2 S3 reference snapshots expire after 30 days; daily database dumps after seven
days. Derived visits, latest positions, quarantine and reference ledgers currently
need operator cleanup: their automated retention policies are not yet implemented.
Set a database growth alarm before an unattended pilot. Do not claim the draft
90-day derived-data retention policy is enforced in this initial slice.

## Backup and restore

V2 installs `tools/backup.sh` as a daily root cron job. It uploads only completed
custom-format pg_dump files. Check cron output at `/var/log/maritime-backup.log`
and backup object timestamps; the OTel backup-age gauge drives a CloudWatch alarm after deployment.

Before operational use, perform this on a separate recovery database using the
same PostgreSQL/Timescale/PostGIS versions:

1. Download the selected dump, verify its size and inspect `pg_restore --list`.
2. Create the target database and compatible extensions using `CREATE EXTENSION IF NOT EXISTS`; the image template may already contain TimescaleDB.
3. Run `SELECT timescaledb_pre_restore();` in the recovery database.
4. Restore with `pg_restore --exit-on-error --no-owner --no-acl` to that database.
5. Run `SELECT timescaledb_post_restore();`.
6. Check extension versions, latest state, history, port geometry and visit counts.
7. Resume ingestion only after deciding how to handle Kafka offsets and potential
   replay; measure restore time and data loss against the selected backup timestamp.

Do not restore into the live database as a test. A successful upload alone does
not establish recoverability. Raw observation archiving is not implemented, so a
database backup plus retained Kafka is the current recovery boundary.

## Deployment changes

Use the V2 runbook and `tools/deploy.py` for content-addressed SSM rollouts and
explicit code rollback. Durable state uses the bootstrap's encrypted/versioned S3
bucket with native lock files. CI cannot create IAM roles, and no automated teardown
is provided. Root EBS is retained on instance termination; retention is not an
automatic restore, and orphan volumes still cost money.

See [V2 deployment](../deploy/v2/README.md) and [OpenTelemetry](telemetry.md).
