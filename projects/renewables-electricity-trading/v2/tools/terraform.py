"""Run Terraform using TF_VAR_* and backend inputs from v2.env."""

import argparse
import json
import os
import subprocess
from environment import ROOT, load_environment


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--env-file")
    p.add_argument("stack", choices=["bootstrap", "dev"])
    p.add_argument("arguments", nargs=argparse.REMAINDER)
    args = p.parse_args()
    load_environment(args.env_file)
    # Let AWS CLI resolve the logged-in SSO profile. Pass short-lived credentials
    # only in memory; this also avoids SDK parsing differences for SSO names.
    if (
        args.arguments
        and args.arguments[0] in ("plan", "apply", "destroy", "refresh", "import", "init")
        and "-backend=false" not in args.arguments
    ):
        result = subprocess.run(
            [
                "aws",
                "configure",
                "export-credentials",
                "--profile",
                os.environ["AWS_DEPLOY_PROFILE"],
                "--format",
                "process",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            p.error("AWS authentication failed; refresh the configured deployment profile")
        credentials = json.loads(result.stdout)
        for source, target in [
            ("AccessKeyId", "AWS_ACCESS_KEY_ID"),
            ("SecretAccessKey", "AWS_SECRET_ACCESS_KEY"),
            ("SessionToken", "AWS_SESSION_TOKEN"),
        ]:
            os.environ[target] = credentials[source]
        os.environ.pop("AWS_PROFILE", None)
    if not args.arguments:
        p.error("Specify a Terraform command")
    required = ["TF_VAR_region", "TF_VAR_state_bucket_name"]
    if args.stack == "dev":
        required += [
            "TF_VAR_name",
            "TF_VAR_bundle_id",
            "TF_VAR_ssh_public_key",
            "TF_VAR_operator_cidr",
            "TF_VAR_client_cidr",
            "TF_VAR_alert_email",
            "TF_VAR_domain_name",
            "TF_VAR_backup_bucket_name",
        ]
    if args.arguments[0] in ("plan", "apply", "destroy", "init"):
        for name in required:
            value = os.environ.get(name, "")
            if (not value and name != "TF_VAR_alert_email") or "REPLACE" in value:
                p.error(f"Configure {name} in v2.env")
    command = ["terraform", f"-chdir={ROOT / 'deploy/terraform' / args.stack}", *args.arguments]
    if (
        args.stack == "dev"
        and args.arguments[0] == "init"
        and "-backend=false" not in args.arguments
    ):
        command += [
            f"-backend-config=bucket={os.environ['TF_VAR_state_bucket_name']}",
            f"-backend-config=key={os.environ['TF_STATE_KEY']}",
            f"-backend-config=region={os.environ['TF_VAR_region']}",
            "-backend-config=encrypt=true",
            "-backend-config=use_lockfile=true",
        ]
    raise SystemExit(subprocess.call(command))


if __name__ == "__main__":
    main()
