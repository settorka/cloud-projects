#!/bin/bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
V2_ENV_FILE=${V2_ENV_FILE:-$(cd "$script_dir/../.." && pwd)/v2.env}
set -a
source "$V2_ENV_FILE"
set +a
for spec in "backup:$BACKUP_SCHEDULE" "check-host:$HEALTH_SCHEDULE"; do
  name=${spec%%:*}
  schedule=${spec#*:}
  cat > "/etc/systemd/system/renewables-$name.service" <<EOF
[Unit]
Description=Renewables $name
[Service]
Type=oneshot
Environment=V2_ENV_FILE=$V2_ENV_FILE
ExecStart=/bin/bash $DEPLOY_ROOT/deploy/aws/$name.sh
EOF
  cat > "/etc/systemd/system/renewables-$name.timer" <<EOF
[Unit]
Description=Renewables $name timer
[Timer]
OnCalendar=$schedule
Persistent=true
[Install]
WantedBy=timers.target
EOF
done
systemctl daemon-reload
systemctl enable --now renewables-backup.timer renewables-check-host.timer
