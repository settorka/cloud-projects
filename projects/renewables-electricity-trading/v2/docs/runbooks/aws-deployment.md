# AWS development deployment

Owner: project operator. Scope: V2 single-host London development environment. Read [the operating contract](../aws-design.md) first. Never use V1's local known tokens on AWS.

## 1. State and plan

From V2, with an authenticated operator AWS profile and Terraform >=1.10:

```sh
cp v2.aws.env.example v2.env
chmod 600 v2.env
# Edit v2.env: real TF_VAR_* values, runtime settings and unique bucket names.
uv run --project services/trading python tools/terraform.py bootstrap init
uv run --project services/trading python tools/terraform.py bootstrap plan
uv run --project services/trading python tools/terraform.py bootstrap apply
uv run --project services/trading python tools/terraform.py dev init
uv run --project services/trading python tools/terraform.py dev plan -out=dev.tfplan
uv run --project services/trading python tools/terraform.py dev apply dev.tfplan
```

Bootstrap state starts local and is ignored: protect and back it up; it owns the remote-state bucket. Import an existing state bucket instead of creating a second owner. Dev state uses encrypted S3, versioning and native lockfiles. Plan/state files are sensitive and must not become CI artifacts. When TF_VAR_alert_email is empty, there is no email subscription or budget notification delivery. Alarms and the budget are console-only; configure and confirm a real email before relying on notifications.

## 2. Images and host configuration

Build each service on a trusted workstation/CI using the operator's ECR push permissions. The runtime user can pull only. Use one immutable Git SHA tag across services:

```sh
aws ecr get-login-password --region eu-west-2 | docker login --username AWS --password-stdin ACCOUNT.dkr.ecr.eu-west-2.amazonaws.com
# Repeat for trading, market-data and valuation; build linux/amd64 for this Lightsail blueprint.
docker buildx build --platform linux/amd64 --push -t REGISTRY/trading:GIT_SHA services/trading
```

Wait for `cloud-init status --wait` over SSH. Terraform's user-data installs Docker/Compose and AWS CLI; it does not install app secrets or start the application. Copy `deploy/aws/` and `deploy/local/init-db.sql` to the matching paths under `/opt/renewables/`; preserve the relative directory layout. Do not copy the local v2.env or virtual environments.

Install an AWS credentials file at `/opt/renewables/credentials/credentials` as described in [credentials](aws-credentials.md). Create `/opt/renewables/v2.env` from `v2.aws.env.example`, mode 0600, root-owned. Set every Terraform output, domain and image SHA; generate independent random passwords and three 40-character hex tokens (`python3 -c 'import secrets; print(secrets.token_hex(20))'`). The deployment seeds explicitly synthetic development identities/domain data; these are not production accounts.

The current development profile needs no purchased domain. It binds Caddy to host loopback and permits only operator SSH ingress. `DOMAIN_NAME=localhost` and `TLS_MODE=internal` use Caddy's private CA. After deployment, establish a workstation tunnel:

```sh
ssh -N -L 8443:127.0.0.1:443 ubuntu@PUBLIC_IP
```

Retrieve `/data/caddy/pki/authorities/local/root.crt` from the Caddy container over authenticated SSH, store it on the workstation, and use `curl --cacert ROOT_CA_FILE https://localhost:8443/health/ready`. Verify the SSH host key and certificate provenance; do not use `--insecure`. Set TLS_CA_FILE to the downloaded CA when using the simulator. This is operator development access, not a public trader endpoint. A public deployment requires a separately reviewed DNS/certificate/ingress configuration.

Run deployment as root on the host:

```sh
bash /opt/renewables/deploy/aws/deploy.sh
```

The script pulls images, stops old APIs/workers before migrations, starts the new version, waits for health and installs backup/heartbeat timers. Deployment involves downtime. First initialization runs migrations and seeds sequentially through the deployment script to limit memory. Failed migration/deployment: keep workers stopped, inspect logs, restore known images/config only if schema-compatible. Do not blindly reverse migrations.

## 3. Acceptance

- Three API containers healthy, three workers running; tunnel profile exposes only SSH to the operator /32.
- HTTPS works through the tunnel with the retrieved CA; direct public HTTP/S is closed.
- Authenticated booking and valuation scenario; duplicate idempotency key does not create a second trade.
- One real EventBridge→SQS→consumer event, plus controlled worker stop/restart; inspect inbox/process history.
- A sampled trace appears in X-Ray and structured logs in the configured CloudWatch group.
- Host heartbeat and successful backup metrics appear; alarm notifications reach the operator.
- Download and restore a backup before accepting the RPO/RTO targets.

These are required AWS acceptance checks, not claims that local validation proves AWS operation. Record commands, image SHA, timestamps and results without credentials.
