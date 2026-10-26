#!/bin/bash
# Run on the host after artifacts and operator-managed configuration are installed.
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
V2_ENV_FILE=${V2_ENV_FILE:-$(cd "$script_dir/../.." && pwd)/v2.env}
cd "$script_dir"
test "$(stat -c %a "$V2_ENV_FILE")" = 600
if grep -q REPLACE "$V2_ENV_FILE"; then echo 'Replace all example values first' >&2; exit 1; fi
set -a
source "$V2_ENV_FILE"
set +a
export AWS_SHARED_CREDENTIALS_FILE="$AWS_CREDENTIALS_DIR/credentials"
registry=${ECR_REGISTRY%%/*}
aws ecr get-login-password --region "$AWS_DEFAULT_REGION" | docker login --username AWS --password-stdin "$registry"
docker compose --env-file "$V2_ENV_FILE" config --quiet
docker compose --env-file "$V2_ENV_FILE" pull
# Migrations must not run concurrently with old workers during deployment.
docker compose --env-file "$V2_ENV_FILE" stop trading trading-worker market-data market-data-worker valuation valuation-worker || true
docker compose --env-file "$V2_ENV_FILE" up -d --wait postgres
for service in trading market-data valuation; do
  docker compose --env-file "$V2_ENV_FILE" run --rm --no-deps "$service-init"
done
docker compose --env-file "$V2_ENV_FILE" up -d --no-deps --wait --wait-timeout "$DEPLOY_WAIT_SECONDS" trading trading-worker market-data market-data-worker valuation valuation-worker caddy otel-collector
/bin/bash install-timers.sh
