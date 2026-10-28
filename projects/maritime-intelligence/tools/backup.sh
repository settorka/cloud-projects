#!/usr/bin/env bash
set -euo pipefail
cd /opt/maritime/current
bucket=$(python3 -c 'import json; print(json.load(open("/opt/maritime/deployment.json"))["bucket"])')
region=$(python3 -c 'import json; print(json.load(open("/opt/maritime/deployment.json"))["region"])')
compose=(docker compose --env-file .env -f deploy/v2/compose.yaml)
pg() { "${compose[@]}" exec -T postgres sh -c 'export PGUSER="$POSTGRES_USER" PGDATABASE="$POSTGRES_DB"; exec "$@"' sh "$@"; }
exec 8>/opt/maritime/backup.lock
flock -n 8 || exit 0
backup_file=$(mktemp /tmp/maritime-backup.XXXXXX)
trap 'rm -f "$backup_file"' EXIT
free_bytes=$(df -PB1 /tmp | awk 'NR==2 {print $4}')
db_bytes=$(pg psql -Atc 'SELECT pg_database_size(current_database())')
[ "$free_bytes" -gt "$((db_bytes + 1073741824))" ] || { echo 'Insufficient backup staging space'; exit 1; }
pg pg_dump -Fc > "$backup_file"
test -s "$backup_file"
key="backups/$(date -u +%Y/%m/%d/%H%M%S).dump"
aws s3 cp "$backup_file" "s3://$bucket/$key" --region "$region" --only-show-errors
printf '%s\n' "$key" > /var/lib/maritime/last-backup-key
touch /var/lib/maritime/backup-success
echo "Backup complete: $key"
