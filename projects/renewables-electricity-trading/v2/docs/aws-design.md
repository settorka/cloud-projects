> Current access profile: SSH tunnel plus Caddy internal TLS, with no purchased domain. Public HTTP/S ingress is disabled. The development configuration currently has no email destination; alarms and the budget are console-only. Existing account costs cannot be verified while Cost Explorer is unavailable. These limitations must be resolved or accepted explicitly before paid deployment.

# V2 AWS development operating contract

This is a constrained, single-host development deployment in London (`eu-west-2`). It is not production-ready. No AWS resources are provisioned by adding these files. Terraform validation is distinct from an authenticated plan and deployment test.

## Components and ownership

One $24/month Lightsail `medium_3_0` IPv4 Linux bundle: 2 burstable vCPUs, 4 GB RAM, 80 GB disk. Caddy terminates HTTPS on loopback, accessed through an SSH tunnel. Three independently built Django services and their workers run in Docker Compose. PostgreSQL runs on the same host with Trading, Market Data and Valuation schemas and separate roles. No public database, OTLP or service ports. SSH is restricted to an operator /32; HTTPS to a configured client CIDR. HTTP port 80 is open for ACME validation and HTTPS redirects. No domain purchase is needed for the tunnel profile.

Market Data ingests external data on explicit operator invocation; no AWS ingestion schedule is enabled by default. Trading and Market Data publish retained outbox deliveries into EventBridge. Rules match a destination, strip the AWS wrapper using `$.detail.envelope`, and deliver to consumer SQS queues. Consumer DLQs and a separate EventBridge routing DLQ have distinct recovery procedures. A successful PutEvents response means bus acceptance, not consumer delivery.

OTLP/HTTP carries spans to a bounded collector, which exports to X-Ray. JSON container logs go through the collector to CloudWatch. Collector logs use Docker's local driver to prevent recursive ingestion. PostgreSQL is authoritative for financial audit, inbox deduplication, source revisions, outbox and process transitions. Sampled traces are diagnostic evidence only.

## Quantified envelope

| Quantity | Configured bound / acceptance target |
|---|---|
| Monthly ceiling | $50 USD total; aim for ~$35 before tax, leaving tax/usage headroom |
| Host / replicas | 1 host; 1 API + 1 worker per service; no autoscaling |
| Application memory | 6 × 256 MiB = 1,536 MiB hard container limits |
| Other steady containers | PostgreSQL 640 MiB + collector 192 MiB + Caddy 96 MiB; ~2,464 MiB total limits excluding init jobs/OS |
| API concurrency | 1 Gunicorn process × 2 threads per API |
| Consumer concurrency | 1 in-flight delivery per consumer worker; guard serializes service application |
| PostgreSQL connections | 40 total; no persistent Django connections |
| Database lock / statement timeout | 2 s / 10 s |
| HTTP body / incoming event | 64 KiB / 256 KiB |
| Worker shutdown / SQS visibility | 40 s grace / 60 s visibility; bounded processing must finish before visibility expires |
| SQS receive wait / retries | 20 s long poll, 25 s SDK read timeout, one SDK attempt per operation; DLQ after 5 receives |
| SQS retention | Main queues 4 days; consumer/routing DLQs 14 days |
| EventBridge routing retries | At most 10 retries within 1 hour; then routing DLQ |
| Load acceptance exercise | 10 trades/s for 5 min = 3,000 attempts; p95 <500 ms, <1% infrastructure failures, zero invariant violations; targets, not results |
| Monthly development allowance | 100,000 trades; 200,000 routed event deliveries; 1,000,000 SQS requests including polls/retries; 10 GB network transfer |
| Database growth | Initial 1 GiB business-data budget; stop ingestion/load work at 10 GiB total DB or 70% root disk usage |
| Backups | Daily pg_dump, <1 GiB per dump; 7-day S3 expiry, no host snapshots enabled by default |
| Recovery | RPO target 24 h, restore target 2 h; unproven until AWS rehearsal |
| Trace sampling | 1%; 100% only for bounded local diagnostic exercises |
| Span buffers | App 512 spans, batches 64, 2 s exporter timeout; collector 192 MiB container /128 MiB limiter |
| Log volume / retention | Operating allowance 20 MiB/day (~600 MiB/month); CloudWatch retention 7 days |
| Local Docker logs | 2 × 5 MiB per long-running container; rotation is independent of CloudWatch retention |
| Trace/process history | Traces sampled; durable process history pruned explicitly after ≥7 days, ≤1,000 attempts per invocation |
| Alerts | DLQ >0 for 1 min; queue age >120 s for 2 min; heartbeat absent/unhealthy for 10 min; disk >70% for 10 min; no backup success for 26 h |

Targets require measurement on the deployed bundle. Memory limits are ceilings, not reservations; init jobs also consume memory. Burstable CPU is not sustained two-core capacity. Start with sequential initialization and one controlled load exercise. No 1,000 trades/s claim, high availability, automatic failover or guaranteed bill cap.

## Economics and bounds

| Allocation | USD/month |
|---|---:|
| Host bundle, public IPv4 and bundled transfer | 24 |
| Backup/state storage and requests | 3 |
| SQS/EventBridge | 2 |
| Logs, bounded metrics, traces and alerts | 5 |
| ECR retained images | 1 |
| Planned pre-tax allocation | 35 |
| Tax/usage headroom to $50 | 15 |

These are allowances, not a quote or hard AWS limit. Other resources in this AWS account consume the same $50 ceiling. Budget notifications at $25/$35/$45 are account-wide and delayed; they do not stop billing. Lightsail continues charging when stopped: delete it to stop host charges after verified backup. Attached static IPs must be released during teardown. Queues, images, backups and state may continue to incur charges. Do not enable automatic host snapshots, NAT gateways, load balancers, RDS, EKS, customer-managed KMS keys or extra hosts within this profile.

One delivery uses roughly a send, receive and delete; 200,000 deliveries imply ~600,000 requests before idle polls, retries or changes of visibility. Two idle consumers at 20 seconds add ~259,200 receives in 30 days. This leaves little room in a one-million-request allowance. Long polls can also delay the shared outbox relay by 20 seconds; a low-latency publish SLO is explicitly not promised by this budget topology.

Process history also costs writes: each normal consumer delivery stores one execution plus five transitions, and a publisher stores one execution plus three transitions. At 200,000 deliveries this is about 2 million rows before additional attempts/indexes. Measure actual bytes and prune terminal diagnostic history regularly; never prune financial audit or inbox/outbox merely to fit the budget. Reduce accepted workload first.

## Credentials and deployment

Lightsail cannot attach an EC2 instance profile. Terraform creates a scoped runtime IAM user but no access keys. An operator installs and rotates credentials out-of-band. This is a documented development compromise: all processes on the host share its AWS permissions. Terraform state, user-data, Git and image layers must never contain runtime secrets. Deploying on EC2 with an instance role is the next option if temporary workload credentials become a requirement; it needs a new cost review.

Terraform and local CI validate configuration without deploying. An AWS operator must supply the account, globally unique bucket names, operator public key/CIDR, existing domain and notification email, then review the authenticated plan. The existing repository OIDC workflow is authentication-only; it is not automatically granted this deployment's broad provisioning permissions.

## Sources

- [Lightsail bundle pricing](https://aws.amazon.com/lightsail/pricing/)
- [Lightsail IAM limitations](https://docs.aws.amazon.com/lightsail/latest/userguide/security_iam_service-with-iam.html)
- [SQS request metering](https://aws.amazon.com/sqs/pricing/)
- [EventBridge target input paths](https://docs.aws.amazon.com/eventbridge/latest/APIReference/API_Target.html)
- [OpenTelemetry Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/)
