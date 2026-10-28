# V2 — AWS deployment

One EC2 host runs the same v1 application, Kafka and TimescaleDB/PostGIS. S3 holds
reference snapshots, releases and backups. EventBridge invokes the reference Lambda.
OpenTelemetry sends application traces, metrics and logs through one collector to
CloudWatch Metrics/Logs and its X-Ray trace integration. No other monitoring stack.

No domain is required: SSM forwards the loopback-bound API over an encrypted tunnel.
All public inbound ports are closed in that mode. Optional HTTPS is supported later.

## Deployment order

1. Merge the reviewed maritime files and `.github/workflows/maritime-aws.yml` to
   `main`; the existing GitHub OIDC trust is restricted to main.
2. An administrator runs the one-time bootstrap below. It creates the protected state
   bucket and runtime IAM roles, and grants the existing GitHub role scoped deployment
   permissions. CI itself cannot create or modify IAM roles.
3. Dispatch **Maritime AWS** with `operation=plan` and the alert email. Review the
   plan and printed commit SHA.
4. Dispatch again with `operation=deploy`, `confirmation=DEPLOY`, and that full SHA
   as `approved_revision`. A changed main branch requires a new reviewed plan.
5. Confirm the SNS email subscription to receive operational alarms.

The approved read-only `MaritimePlanRead` policy has already been attached. The full
bootstrap/deployment policy has only been prepared and validated, not attached.

## One-time administrative bootstrap

From the project directory, using an administrative AWS identity:

```sh
uv sync --frozen --group deploy
uv run --group deploy python tools/aws_bootstrap.py
```

This is a dry run: it reads account identity and writes ignored
`dist/github-deployment-policy.json` and `dist/backend.hcl`. Review the policy.
To perform the bootstrap deliberately:

```sh
uv run --group deploy python tools/aws_bootstrap.py --apply
```

The script preserves GitHub OIDC trust, refuses to overwrite unowned runtime roles,
uses a private encrypted/versioned S3 state bucket, and grants deletion only of the
state lock object, not the state itself. It creates no compute resources. Keep its
bucket/roles separate from application teardown. They incur small S3 storage/request
costs once used. Runtime roles have only their own data/log/tracing permissions.

The optional `deploy` dependency group supports the local `aws login` credential
provider. CI uses short-lived OIDC credentials; no stored AWS access keys are needed.

## What the workflow does

- Tests and packages a deterministic release, excluding local secrets.
- Uses S3 Terraform state with native lock files; no DynamoDB table is required.
- Plans and refuses deletions/replacements, IAM mutations or unbudgeted services.
- Applies the saved plan only on a manually confirmed deploy run.
- Uses SSM to build/start the release; checksum verification precedes extraction.
- Preserves API/database credentials across application updates.
- Checks authenticated API readiness, fresh real AIS data and Lambda reference import.
- Takes a backup, restores it into a disposable database, and checks collector status.

The plan is regenerated on the deploy run against current AWS state and guarded
before applying; the commit check prevents deploying unreviewed code. This is a
single-host development deployment, not a production availability guarantee.

## Local Terraform inspection

For schema/mocked checks before bootstrap:

```sh
uv run python tools/package_release.py
terraform -chdir=deploy/v2/terraform init -backend=false
terraform -chdir=deploy/v2/terraform validate
terraform -chdir=deploy/v2/terraform test
```

After bootstrap, an authorized operator can use its remote state:

```sh
cp deploy/v2/terraform/backend.tf.example deploy/v2/terraform/backend.auto.tf
terraform -chdir=deploy/v2/terraform init -reconfigure -backend-config=../../../dist/backend.hcl
terraform -chdir=deploy/v2/terraform plan -var-file=development.tfvars.json
```

Use `-reconfigure` only for this new stack with no applied local resources. If local
state already manages resources, migrate it explicitly instead of abandoning it.
The GitHub workflow always configures the same remote state bucket/key.

## Access, verification and code rollback

```sh
uv run python tools/deploy.py tunnel
uv run --group deploy python tools/deploy.py verify
uv run --group deploy python tools/deploy.py backup
uv run --group deploy python tools/deploy.py restore-check
```

`tunnel` prints the SSM port-forwarding command. Run it, then use
`http://127.0.0.1:8200/docs`. Root-only `/opt/maritime/.env` contains the generated API
credential; retrieve it privately through an authorized SSM session, never CI logs.

A reviewed previous release can be redeployed through `tools/deploy.py deploy
--artifact artifacts/<previous-sha256>.tar.gz`. This rolls back application code,
not schema/data. Review migration compatibility first. Releases live under
`/opt/maritime/releases`; `current` and `previous` identify successful releases.
After a failed rollout inspect SSM/cloud-init output before retrying. Docker layers
and old release directories require periodic disk review; no destructive pruning
runs automatically. An AMI replacement likewise requires backup/recovery review.

## CloudWatch and cost

[CloudWatch London console](https://eu-west-2.console.aws.amazon.com/cloudwatch/home?region=eu-west-2)

- Logs: `/maritime-intelligence/application`, fourteen-day retention.
- Metrics: namespace `MaritimeIntelligence`; EMF source log group
  `/maritime-intelligence/metrics`, fourteen-day retention.
- Traces: CloudWatch's X-Ray integration. Root traces default to 1% sampling.
- Alarms: EC2 status, free disk fraction, backup age and Lambda errors, delivered by SNS.
- Lambda retains its native CloudWatch execution logs. Application SDK telemetry
  covers the API and container workers; no Lambda OTel extension is installed.

Endpoint, sampling, export interval and collector limits are grouped in `.env`.
Secrets, SQL parameters, raw request URLs and vessel IDs are excluded from span
attributes and metric dimensions. Metrics use bounded project/service dimensions.
Collector ports are private to the Compose network. AWS credentials come from the
instance profile, and collector IAM is scoped to the application log groups plus
X-Ray ingestion. Filesystem collection uses a read-only host mount.

The documented London EC2/disk/IPv4 fixed model is $76.24 for a 31-day month. Allow
$12/month initially for telemetry, S3 and minor services: at assumed £0.85/USD and
20% VAT that totals about **£90/month**. This is an allowance, not a guaranteed bill
or live FX quote. Review actual trace/log volume before broadening coverage.
The account-wide budget is notification-only. No free-tier credit is required.

No application infrastructure has been applied during implementation. The first
cloud deployment must establish live CloudWatch delivery and recovery acceptance.
