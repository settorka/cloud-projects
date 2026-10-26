# V2 environment configuration

`v2.env` at the V2 project root is the canonical configuration file for the selected environment. It is gitignored and must be mode 0600. V1 is unchanged.

## Local use

```sh
cp v2.env.example v2.env
chmod 600 v2.env
make up
make test
make e2e
```

A local `v2.env` has already been initialized from the local template in this working checkout. It contains local-only example credentials. The file itself is not committed.

## AWS use

Copy `v2.aws.env.example` to `v2.env` in a separate deployment checkout or on the host. Fill account-specific values, DNS, image SHA, random secrets and TF_VAR_* inputs before deployment. Never overwrite a local file containing wanted configuration without preserving it first. Both templates use the same key set. They are alternative starting profiles, not two files loaded simultaneously.

Compose interpolation: `docker compose --env-file v2.env …` from the V2 root. AWS Compose: `V2_ENV_FILE="$PWD/v2.env" docker compose --env-file v2.env -f deploy/aws/compose.yaml …`. Make exports the absolute V2_ENV_FILE path automatically. Explicit process environment values take precedence in Python loading and Compose interpolation. Container env_file values are overridden only by explicit Compose environment entries, following native Compose behavior. Keep values compatible with dotenv and shell assignment syntax; quote values containing spaces, including SSH public keys and JSON objects.

Each service loads the selected file for direct host execution, or consumes environment variables injected by Compose. It resolves DB_USER/DB_PASSWORD/DB_SCHEMA overrides first (used by isolated tests), then its service-specific settings such as TRADING_DB_USER. Missing required settings fail rather than choosing a built-in region, credential, endpoint or port. Docker images do not contain v2.env.

Host tools use the same loader and accept V2_ENV_FILE; E2E/recovery tools also accept --env-file. `--env-file` selects a file, while an explicitly exported environment value still wins. For direct Django execution, use `V2_ENV_FILE=/absolute/path/v2.env uv run --project services/trading python services/trading/manage.py …`; adjust DB_HOST/DB_PORT to an actually reachable database rather than a Compose-only hostname.

## Terraform

Terraform itself does not read dotenv files. The launcher loads v2.env and forwards native TF_VAR_* environment variables. It supplies S3 backend settings during dev initialization without putting runtime secrets in Terraform variables or state.

```sh
uv run --project services/trading python tools/terraform.py bootstrap init
uv run --project services/trading python tools/terraform.py bootstrap plan
uv run --project services/trading python tools/terraform.py bootstrap apply
uv run --project services/trading python tools/terraform.py dev init
uv run --project services/trading python tools/terraform.py dev plan -out=dev.tfplan
uv run --project services/trading python tools/terraform.py dev apply dev.tfplan
```

`TF_VAR_operating` holds retention, queue and alarm tuning as JSON. Reviewed safety constraints remain in Terraform validation. Supplying another environment profile does not authorize spending beyond the $50 budget. The Terraform launcher resolves AWS_DEPLOY_PROFILE through AWS CLI into short-lived process credentials; it never stores those credentials in v2.env or Terraform state. AWS credentials use the standard external AWS credential chain; the host runtime credential file is installed separately, not stored in v2.env.

## What stays in code

Event schemas, state-machine edges, financial formulas, API routes, service ownership, test fixtures, build dependency locks and reviewed security/budget guardrails remain versioned code. They are not deployment variables. Application/container ports inside the Compose network remain part of the interface contract; public bind addresses and ports are configurable.

Changing an existing database name, role or schema in v2.env is not a database migration. The init SQL reads those values only when creating a fresh PostgreSQL data directory. Existing volumes require a reviewed migration or a separate fresh environment. Never delete a wanted database volume just to apply a configuration change.

The currently selected v2.env is the AWS development profile. The previous local profile is preserved in ignored v2.local.env; run local commands with `make ENV_FILE=v2.local.env …`. AWS_ACCOUNT_ID is informational; TF_VAR_aws_account_id enforces the Terraform target account.
