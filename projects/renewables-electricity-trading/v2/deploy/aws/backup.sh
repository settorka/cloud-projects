#!/bin/bash
# Run as root via the installed systemd timer. No passwords on command lines.
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
V2_ENV_FILE=${V2_ENV_FILE:-$(cd "$script_dir/../.." && pwd)/v2.env}
cd "$script_dir"
set -a
source "$V2_ENV_FILE"
set +a
export AWS_SHARED_CREDENTIALS_FILE="$AWS_CREDENTIALS_DIR/credentials"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
file=$DEPLOY_ROOT/backups/$stamp.dump
trap 'rm -f "$file"' EXIT
docker compose --env-file "$V2_ENV_FILE" exec -T postgres pg_dump -U postgres -d "$DB_NAME" -Fc > "$file"
# Refuse unexpected growth before uploading.
test "$(stat -c %s "$file")" -lt "$BACKUP_MAX_BYTES"
aws s3 cp "$file" "s3://$BACKUP_BUCKET/postgres/$stamp.dump" --only-show-errors
aws cloudwatch put-metric-data --namespace Renewables/V2 --metric-data MetricName=BackupSucceeded,Value=1,Unit=Count
