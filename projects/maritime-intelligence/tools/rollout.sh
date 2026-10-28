#!/usr/bin/env bash
# Run as root on the AWS host, with /opt/maritime/deployment.json already installed.
set -euo pipefail
bucket=$1
artifact=$2
region=$3
[[ "$artifact" =~ ^artifacts/([a-f0-9]{64})\.tar\.gz$ ]] || { echo 'Invalid release key'; exit 2; }
release_hash=${BASH_REMATCH[1]}
base=/opt/maritime
release="$base/releases/$release_hash"
install -d -m 700 "$base/releases"
install -d -m 755 /var/lib/maritime
exec 9>"$base/rollout.lock"
flock -n 9 || { echo 'Another rollout is active'; exit 1; }
archive=$(mktemp /tmp/maritime-release.XXXXXX)
trap 'rm -f "$archive"' EXIT
aws s3 cp "s3://$bucket/$artifact" "$archive" --region "$region" --only-show-errors
printf '%s  %s\n' "$release_hash" "$archive" | sha256sum -c - >/dev/null
install -d -m 700 "$release"
python3 - "$archive" "$release" <<'PY'
import sys, tarfile
with tarfile.open(sys.argv[1]) as archive:
    archive.extractall(sys.argv[2], filter='data')
PY
python3 "$release/tools/configure_host.py" "$base" "$release"

cd "$release"
compose=(docker compose --env-file .env -f deploy/v2/compose.yaml)
# Build before touching running services. Migrations are checksum-checked/additive.
"${compose[@]}" build migrate
"${compose[@]}" up -d --wait postgres kafka
"${compose[@]}" run --rm --no-deps kafka-init
if [ -L "$base/current" ]; then /usr/local/sbin/maritime-backup; fi
"${compose[@]}" run --rm --no-deps migrate
"${compose[@]}" up -d --remove-orphans
# Authenticated read; does not mistake process liveness for database readiness.
healthy=false
for attempt in $(seq 1 30); do
  if "${compose[@]}" exec -T api python - <<'PY'
import json, os, urllib.request
request=urllib.request.Request('http://127.0.0.1:' + os.environ['API_PORT'] + '/v1/status',
    headers={'Authorization':'Bearer ' + os.environ['API_TOKEN']})
with urllib.request.urlopen(request, timeout=5) as response:
    assert json.load(response)['database'] == 'ready'
PY
  then healthy=true; break; fi
  sleep 5
done
if [ "$healthy" != true ]; then
  echo 'Release failed health check; previous release pointer preserved. Review migrations before rollback.'
  exit 1
fi
previous=$(readlink "$base/current" || true)
if [ -n "$previous" ] && [ "$previous" != "$release" ]; then
  ln -sfn "$previous" "$base/previous"
fi
ln -sfn "$release" "$base/current"
install -m 700 tools/backup.sh /usr/local/sbin/maritime-backup
install -m 700 tools/restore_check.sh /usr/local/sbin/maritime-restore-check
printf '17 2 * * * root /usr/local/sbin/maritime-backup >> /var/log/maritime-backup.log 2>&1\n' > /etc/cron.d/maritime-backup
rm -f /etc/cron.d/maritime-metrics /usr/local/sbin/maritime-host-metrics
printf '%s\n' "$release_hash" > /var/lib/maritime/release
# Take a first verified-completion backup rather than waiting until tonight.
/usr/local/sbin/maritime-backup
echo "Release ready: $release_hash"
