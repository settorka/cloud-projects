"""Remove temporary Bastion infrastructure while preserving the warehouse and VM."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TF = ROOT / "terraform"


def main():
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/connect_dashboard.py"), "--stop"],
        check=True,
    )
    config = TF / "local.auto.tfvars.json"
    values = json.loads(config.read_text())
    values.update(enable_bastion=False, allowed_client_cidr=None)
    config.write_text(json.dumps(values, indent=2) + "\n")
    os.chmod(config, 0o600)
    prefix = ["terraform", "-chdir=" + str(TF)]
    plan = "bastion-off.tfplan"
    subprocess.run(prefix + ["plan", "-input=false", "-out=" + plan], check=True)
    os.chmod(TF / plan, 0o600)
    detail = json.loads(subprocess.check_output(prefix + ["show", "-json", plan]))
    permitted = {
        "azurerm_bastion_host.fx[0]",
        "azurerm_public_ip.bastion[0]",
        "azurerm_subnet.bastion[0]",
    }
    for resource in detail.get("resource_changes", []):
        actions = resource["change"]["actions"]
        if actions in (["no-op"], ["read"]):
            continue
        if resource["address"] in permitted and actions == ["delete"]:
            continue
        if (
            resource["address"] == "azurerm_network_security_group.fx[0]"
            and actions == ["update"]
            and all(
                rule["access"] == "Deny"
                for rule in resource["change"]["after"]["security_rule"]
            )
        ):
            continue
        raise SystemExit("Unexpected change; refusing teardown: " + resource["address"])
    subprocess.run(prefix + ["apply", "-input=false", plan], check=True)
    print(
        "Bastion removed; VM and warehouse preserved. Public inbound access remains closed."
    )


if __name__ == "__main__":
    main()
