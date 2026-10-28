# Verification — 28 October 2026

- Application code is in `src/v1`, with external integrations in `adapters`.
- Grouped `.env` configuration and Compose overrides are validated; no local secrets
  are included in the release or Lambda configuration.
- Local integration suite passed with real Kafka, TimescaleDB/PostGIS and S3.
- OpenTelemetry tests verify HTTP/database spans, producer-to-consumer propagation,
  bounded metric labels, sensitive-data exclusion and disabled-export behaviour.
- The CloudWatch collector configuration validates with pinned collector 0.164.0.
- Terraform schema validation and both mocked deployment plans pass.
- Bootstrap policy validation through AWS Access Analyzer returned no findings.
- The approved read-only `MaritimePlanRead` policy was attached to the GitHub role.
  No application compute, state bucket, CloudWatch groups or runtime roles were
  provisioned. Broader bootstrap permissions remain prepared, not attached.

The first cloud deployment still needs the one-time administrative bootstrap,
main-branch workflow publication, manual plan review and confirmed deploy. It must
verify actual CloudWatch delivery, source freshness and backup restoration. Local
checks do not establish AWS uptime SLOs, complete European coverage or a hard bill cap.
