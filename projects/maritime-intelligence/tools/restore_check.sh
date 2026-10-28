#!/usr/bin/env bash
# Restore only into a disposable database, never the live database.
set -euo pipefail
cd /opt/maritime/current
bucket=$(python3 -c 'import json; print(json.load(open("/opt/maritime/deployment.json"))["bucket"])')
region=$(python3 -c 'import json; print(json.load(open("/opt/maritime/deployment.json"))["region"])')
key=${1:-$(cat /var/lib/maritime/last-backup-key)}
[[ "$key" =~ ^backups/[0-9/]+\.dump$ ]] || { echo 'Invalid backup key'; exit 2; }
file=$(mktemp /tmp/maritime-restore.XXXXXX)
restore_db="maritime_restore_$(date +%s)_$RANDOM"
compose=(docker compose --env-file .env -f deploy/v2/compose.yaml)
pg() { "${compose[@]}" exec -T postgres sh -c 'export PGUSER="$POSTGRES_USER" PGDATABASE="$POSTGRES_DB"; exec "$@"' sh "$@"; }
cleanup() { pg dropdb --if-exists "$restore_db" >/dev/null; rm -f "$file"; }
trap cleanup EXIT
free_bytes=$(df -PB1 /tmp | awk 'NR==2 {print $4}')
dump_bytes=$(aws s3api head-object --bucket "$bucket" --key "$key" --region "$region" --query ContentLength --output text)
db_bytes=$(pg psql -Atc 'SELECT pg_database_size(current_database())')
[ "$free_bytes" -gt "$((db_bytes + dump_bytes + 1073741824))" ] || { echo 'Insufficient space for isolated restore check'; exit 1; }
aws s3 cp "s3://$bucket/$key" "$file" --region "$region" --only-show-errors
pg createdb "$restore_db"
pg psql -d "$restore_db" -v ON_ERROR_STOP=1 \
 -c 'CREATE EXTENSION IF NOT EXISTS timescaledb; CREATE EXTENSION IF NOT EXISTS postgis; SELECT timescaledb_pre_restore();' >/dev/null
pg pg_restore --exit-on-error --no-owner --no-acl -d "$restore_db" < "$file"
pg psql -d "$restore_db" -v ON_ERROR_STOP=1 -c 'SELECT timescaledb_post_restore(); SELECT count(*) AS restored_observations FROM positions;'
echo 'Restore check passed; live database untouched'
