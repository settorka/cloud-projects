"""Operate a Terraform-managed host through SSM; no SSH or exposed API required."""

import argparse
import base64
import json
import re
import shlex
import subprocess
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]


def outputs(directory):
    data = json.loads(
        subprocess.check_output(["terraform", "-chdir=" + str(directory), "output", "-json"])
    )
    return {key: value["value"] for key, value in data.items()}


def rollout_commands(config, artifact):
    if not re.fullmatch(r"artifacts/[a-f0-9]{64}\.tar\.gz", artifact):
        raise ValueError("Expected a content-addressed release artifact")
    document = base64.b64encode(json.dumps(config, sort_keys=True).encode()).decode()
    bucket, region = shlex.quote(config["bucket"]), shlex.quote(config["region"])
    source = shlex.quote("s3://" + config["bucket"] + "/" + artifact)
    digest = artifact.removeprefix("artifacts/").removesuffix(".tar.gz")
    body = f"""set -euo pipefail
cloud-init status --wait || echo 'Cloud-init reported a failure; attempting the reviewed rollout'
install -d -m 700 /opt/maritime
printf %s {shlex.quote(document)} | base64 -d > /opt/maritime/deployment.json
work=$(mktemp -d /tmp/maritime-rollout.XXXXXX)
trap 'rm -rf "$work"' EXIT
aws s3 cp {source} "$work/release.tar.gz" --region {region} --only-show-errors
printf '%s  %s\\n' {digest} "$work/release.tar.gz" | sha256sum -c - >/dev/null
tar -xzf "$work/release.tar.gz" -C "$work" tools/rollout.sh
bash "$work/tools/rollout.sh" {bucket} {shlex.quote(artifact)} {region}
"""
    return ["bash -se <<'MARITIME_SCRIPT'\n" + body + "\nMARITIME_SCRIPT"]


def wait_online(client, instance, timeout=1200):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = client.describe_instance_information(
            Filters=[{"Key": "InstanceIds", "Values": [instance]}]
        )["InstanceInformationList"]
        if any(row["PingStatus"] == "Online" for row in rows):
            return
        time.sleep(10)
    raise TimeoutError("SSM agent did not become available; inspect EC2/cloud-init diagnostics")


def run(client, instance, commands, timeout=1800):
    sent = client.send_command(
        InstanceIds=[instance],
        DocumentName="AWS-RunShellScript",
        TimeoutSeconds=600,
        Parameters={"commands": commands, "executionTimeout": [str(timeout)]},
    )
    identity = sent["Command"]["CommandId"]
    print("SSM command:", identity, flush=True)
    deadline = time.monotonic() + timeout + 60
    while time.monotonic() < deadline:
        try:
            result = client.get_command_invocation(CommandId=identity, InstanceId=instance)
        except client.exceptions.InvocationDoesNotExist:
            time.sleep(5)
            continue
        if result["Status"] not in {"Pending", "InProgress", "Delayed"}:
            print(result.get("StandardOutputContent", ""))
            if result["Status"] != "Success":
                raise RuntimeError(result["Status"] + ": " + result.get("StandardErrorContent", ""))
            return result
        time.sleep(5)
    raise TimeoutError("SSM command timed out; inspect its status before retrying")


def verify(session, info, client):
    response = session.client("lambda").invoke(
        FunctionName=info["reference_function"], Payload=b"{}"
    )
    payload = json.loads(response["Payload"].read())
    if response.get("FunctionError") or not payload.get("object_key"):
        raise RuntimeError("Reference Lambda verification failed")
    body = """set -euo pipefail
cd /opt/maritime/current
docker compose --env-file .env -f deploy/v2/compose.yaml exec -T references python -m v2.bootstrap import
for attempt in $(seq 1 30); do
 if docker compose --env-file .env -f deploy/v2/compose.yaml exec -T api python - <<'PYTHON'
import json, os, urllib.request
from v1.settings import Settings
from v1.adapters.postgres import PostgresRepository
request=urllib.request.Request('http://127.0.0.1:'+os.environ['API_PORT']+'/v1/status',
    headers={'Authorization':'Bearer '+os.environ['API_TOKEN']})
with urllib.request.urlopen(request,timeout=5) as response: status=json.load(response)
assert status['database']=='ready'
assert status['data_freshness']=='fresh', 'Awaiting fresh real AIS observations'
with PostgresRepository(Settings.load()).connect() as connection:
    assert connection.execute('SELECT count(*) AS n FROM reference_imports').fetchone()['n']>0
print(json.dumps({'database':'ready','real_ais':'fresh','reference_snapshot':'imported'}))
PYTHON
 then break; fi
 [ "$attempt" -lt 30 ] || exit 1
 sleep 5
done
/usr/local/sbin/maritime-backup
/usr/local/sbin/maritime-restore-check
docker compose --env-file .env -f deploy/v2/compose.yaml ps --status running --services | grep -qx otel-collector
"""
    run(
        client, info["instance_id"], ["bash -se <<'MARITIME_VERIFY'\n" + body + "\nMARITIME_VERIFY"]
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["deploy", "verify", "backup", "restore-check", "tunnel"])
    parser.add_argument("--terraform-dir", type=Path, default=ROOT / "deploy/v2/terraform")
    parser.add_argument(
        "--artifact", help="Reviewed older artifact key for an explicit code rollback"
    )
    args = parser.parse_args()
    info = outputs(args.terraform_dir)
    if args.action == "tunnel":
        print(info["ssm_tunnel_command"])
        return
    session = boto3.Session(region_name=info["region"])
    client = session.client("ssm")
    wait_online(client, info["instance_id"])
    if args.action == "deploy":
        run(
            client,
            info["instance_id"],
            rollout_commands(info["deployment_config"], args.artifact or info["artifact"]),
        )
        verify(session, info, client)
    elif args.action == "verify":
        verify(session, info, client)
    else:
        command = (
            "/usr/local/sbin/maritime-backup"
            if args.action == "backup"
            else "/usr/local/sbin/maritime-restore-check"
        )
        run(client, info["instance_id"], [command])


if __name__ == "__main__":
    main()
