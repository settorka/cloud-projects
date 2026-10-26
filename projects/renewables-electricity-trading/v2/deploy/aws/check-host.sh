#!/bin/bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
V2_ENV_FILE=${V2_ENV_FILE:-$(cd "$script_dir/../.." && pwd)/v2.env}
cd "$script_dir"
set -a
source "$V2_ENV_FILE"
set +a
export AWS_SHARED_CREDENTIALS_FILE="$AWS_CREDENTIALS_DIR/credentials"
healthy=1
for service in trading market-data valuation; do
  docker compose exec -T "$service" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready', timeout=3)" >/dev/null 2>&1 || healthy=0
  docker compose exec -T "$service" python manage.py operational_snapshot --cloudwatch >/dev/null 2>&1 || healthy=0
done
disk=$(df --output=pcent / | tail -1 | tr -dc '0-9')
aws cloudwatch put-metric-data --namespace Renewables/V2 --metric-data "MetricName=HostHealthy,Value=$healthy,Unit=Count" "MetricName=DiskUsedPercent,Value=$disk,Unit=Percent"
