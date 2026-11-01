"""Execute SQL files on the development VM; fail if guest execution fails."""

import argparse
import base64
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--resource-group", default="rg-fx-warehouse-dev")
    parser.add_argument("--vm", default="vm-fx-dev")
    args = parser.parse_args()
    payload = b"\nGO\n".join(path.read_bytes() for path in args.files)
    wrapper = Path(__file__).with_name("deploy-schema.ps1").resolve()
    encoded = base64.b64encode(payload).decode()
    remote_script = wrapper.read_text().replace(
        "param([Parameter(Mandatory = $true)][string]$schemaBase64)",
        f"$schemaBase64 = '{encoded}'",
        1,
    )
    result = subprocess.run(
        [
            "az",
            "vm",
            "run-command",
            "invoke",
            "-g",
            args.resource_group,
            "-n",
            args.vm,
            "--command-id",
            "RunPowerShellScript",
            "--scripts",
            remote_script,
            "-o",
            "json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    messages = json.loads(result.stdout)["value"]
    output = "\n".join(item.get("message", "") for item in messages)
    print(output)
    # Azure can report the operation succeeded even if PowerShell/sqlcmd failed.
    if "FX_SQL_SUCCESS" not in output.splitlines():
        raise SystemExit("Guest SQL execution failed; success marker absent.")


if __name__ == "__main__":
    main()
