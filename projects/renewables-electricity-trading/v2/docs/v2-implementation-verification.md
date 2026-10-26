# V2 implementation verification

Verified locally on 26 October 2026. No AWS resources were created, no authenticated AWS plan was applied, and no AWS performance/recovery result is claimed.

## Measured and executed

- PostgreSQL regression: **65 passed** — Trading 30, Market Data 19, Valuation 16.
- Includes trace continuation through persisted outbox and SQS delivery, unsampled durable lineage, application rollback, failed acknowledgement/redelivery, invalid envelopes, illegal transitions, EventBridge partial failure, ingestion success/failure and bounded diagnostic-history retention.
- Ruff checks, formatting and canonical event schemas pass. Shared operational helper copies are checked for drift across independently built services.
- Terraform bootstrap and dev initialize and validate with locked AWS provider 6.70.0. Four mocked plan tests pass: budget profile, rejection of public SSH, rejection of an unreviewed host size and rejection of unrestricted HTTPS. These do not test AWS permissions or resource availability.
- AWS Compose resolves using example configuration; AWS/local collector configurations validate against collector 0.139.0; HTTPS configuration validates against Caddy 2.10.2. Shell scripts pass `bash -n`.
- Full local traced HTTP/broker E2E passed: booking, retry, position, valuation, worker recovery, forecast breach, cover, reconciliation, authorization and schema isolation.
- Collector inspection observed 42 exported traces, including two complete booking→publication→consumption traces. One contained `POST v1/trades`, `trading.book`, `trading.locked_portfolio`, `outbox.publish`, `event.consume` and `valuation.calculate` under one trace ID. This is local exporter evidence, not proof of X-Ray delivery.
- V1 application files were not modified. Environment files, credential directories, Terraform state/plans and actual tfvars are ignored; examples and provider locks remain trackable.

## Bounded local latency sample

With 100% local trace sampling: 100 attempts at 10 requests/s, all 100 sent, zero generator shedding, 90 HTTP 201 responses and 10 business HTTP 422 rejections, no infrastructure errors. p50 18.2 ms, p95 25.7 ms, p99 89.4 ms; elapsed 9.92 seconds. This tiny workstation sample is not an AWS capacity result or proof of the 3,000-attempt acceptance target. The simulator records raw requests outside Git; post-run position reconciliation reported zero mismatches.

## Required before calling AWS deployment accepted

Provide real account/region inputs, unique bucket names, operator public key/CIDR, existing DNS name, notification email and out-of-band runtime credentials. Review the authenticated Terraform plan. Confirm AWS EventBridge routing/SQS delivery, IAM scopes, TLS/ingress, X-Ray/CloudWatch delivery, notifications, backup upload and isolated restore using the deployment runbook. Measure the 3,000-attempt load exercise, queue catch-up, peak memory/disk and cost. RPO 24 h, restore 2 h, p95 <500 ms and $35 pre-tax allocation are targets/allowances, not achieved AWS results.

## Environment configuration follow-up

V2 runtime configuration now loads from ignored `v2.env`, grouped by entity with short comments. Local and AWS templates have identical key sets. Compose, direct Django execution, operator tools, collectors and the Terraform launcher consume this configuration. Environment-file mode 0600, loader precedence and missing-file failure were checked. All 65 PostgreSQL tests, four Terraform mocked plans, lint/contracts and the traced E2E scenario passed again after this migration.

## AWS preflight

The dev SSO identity was verified for the intended account. AWS confirmed London medium_3_0 is active at $24/month and Ubuntu 24.04 is available. Inspected S3 buckets, Lightsail/EC2 hosts, RDS instances, EBS volumes and allocated EC2 IPs in London/Stockholm were empty. This is not a complete account cost audit: Cost Explorer returned access-not-enabled, so month-to-date spending remains unverified. A real bootstrap plan was generated without applying it. Five mocked development plans pass, including tunnel-only access with no email subscription. No domain/email details were fabricated.

Authenticated plans: bootstrap proposes 5 creates; an isolated pre-bootstrap preview of the complete development stack proposes 47 creates, zero updates and zero deletes. No resources were applied. The preview uses a temporary local backend solely for review; initialize the real S3 backend and re-plan after reviewed bootstrap before any development apply. Tunnel-only/internal-TLS configuration validates. Account-specific values, generated secrets, public-key selection and the previous local profile remain in ignored environment files; no temporary AWS session credentials were written into them.
