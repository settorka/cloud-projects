# V2 operating runbooks

AWS development:

- [Deployment and acceptance](aws-deployment.md)
- [Credentials and rotation](aws-credentials.md)
- [Observability and incident triage](aws-observability.md)
- [Queue/database recovery and rollback](aws-recovery.md)
- [Cost and capacity control](aws-cost-capacity.md)

The following inherited procedures target the local Compose environment. AWS uses `deploy/aws/compose.yaml`, real SQS/EventBridge, root-operated timers and separate recovery credentials. Do not substitute local ElasticMQ reset or broker-loss commands on AWS.

# Runbook index

Run commands from the project directory. Examples use `v2.env`; substitute `v2.env.example` for an unchanged demonstration configuration. Never paste tokens into shared incident reports.

- [Startup](local-startup.md)
- [Reset and stop](local-reset.md)
- [Booking failures](booking-failures.md)
- [Queue recovery](queue-recovery.md)
- [Market-data failures](market-data-failures.md)
- [Position reconciliation](position-reconciliation.md)
- [Valuation failures](valuation-failures.md)
- [Database backup and restore](database-backup-restore.md)
- [Load testing](load-testing.md)

Owner: the local developer. Diagnose first, contain the affected workflow, recover, verify business state, then record findings. Do not blindly replay messages, erase volumes or rerun requests with new keys after unknown outcomes.
