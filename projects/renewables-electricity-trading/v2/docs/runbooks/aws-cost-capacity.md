# Cost and capacity control

Owner: project operator. Monthly ceiling: $50 USD including applicable tax and other account resources. Planned project allocation ~$35 pre-tax. No credits assumed. AWS Budgets notifications are delayed alerts, not a hard cap.

At $25 actual account spend, inspect service/region breakdown and forecast. At $35, stop load tests and optional ingestion, review retained logs/images/backups and decide whether to keep the host. At $45, preserve and verify the latest backup, then delete the host and unneeded resources if further spend would breach the ceiling. Stopping Lightsail does not stop host charges. Terraform prevents backup/state bucket deletion by default.

Daily during development: inspect queue requests/backlog, CloudWatch incoming bytes, ECR bytes, S3 bytes, database size and root disk. Keep ≤5 MiB logs/day, ≤1 GiB backup, seven daily backups, three retained images per service, 1% tracing and no high-cardinality metric dimensions. These are operating allowances, not service-side billing caps. Do not add resources without updating the estimate.

Before load testing, confirm backup success, disk <70%, no DLQ backlog and adequate Lightsail burst capacity. Run the external simulator from the workstation at 10 trades/s for 300 seconds. Report attempted, accepted, rejected, infrastructure failures, generator shedding, p50/p95/p99, oldest queue age, worker lag, disk and CPU. Business limit rejections are not server errors. Confirm the generator actually delivered the requested rate. Reconcile positions after the run. The target is p95 <500 ms, <1% infrastructure errors and zero financial invariant violations; this is not yet an AWS measurement.

Never run sustained 1,000 trades/s within this profile. At 100,000 trades/month, event fanout, inbox retention and per-attempt lineage writes can dominate storage before HTTP traffic dominates cost. Measure rows and bytes per trade; lower admitted traffic or archive reviewed diagnostic history before increasing machine size. Do not delete deduplication history without a documented replay horizon.
