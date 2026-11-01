"""Open or close a host-key-verified, loopback-only SSH dashboard tunnel."""

import argparse
import hashlib
import ipaddress
import json
import os
import signal
import socket as network_socket
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCESS = ROOT / "data" / "access"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    state_path = ACCESS / "connection.json"
    socket_dir = (
        Path("/tmp")
        / f"fxssh-{os.getuid()}-{hashlib.sha256(str(ROOT).encode()).hexdigest()[:8]}"
    )
    socket_dir.mkdir(mode=0o700, exist_ok=True)
    mode = socket_dir.stat()
    if mode.st_uid != os.getuid() or mode.st_mode & 0o077:
        raise SystemExit("SSH control directory is not private")
    socket = socket_dir / "control.sock"
    if args.stop:
        if state_path.exists():
            address = json.loads(state_path.read_text())["address"]
            subprocess.run(
                ["ssh", "-S", str(socket), "-O", "exit", f"fxadmin@{address}"],
                check=False,
            )
            pid = json.loads(state_path.read_text()).get("bastion_pid")
            if pid:
                command = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "command="],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout
                if "network bastion tunnel" in command and "bastion-fx-dev" in command:
                    os.kill(pid, signal.SIGTERM)
            state_path.unlink(missing_ok=True)
        return
    key = ACCESS / "fx_vm_ed25519"
    if not key.exists():
        raise SystemExit(
            "Transport key is missing; run the documented SSH provisioning step first."
        )
    address = subprocess.check_output(
        [
            "terraform",
            "-chdir=" + str(ROOT / "terraform"),
            "output",
            "-raw",
            "windows_public_ip",
        ],
        text=True,
    ).strip()
    address = str(ipaddress.ip_address(address))
    if (
        subprocess.run(
            ["ssh", "-S", str(socket), "-O", "check", f"fxadmin@{address}"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    ):
        print("Dashboard tunnel already available: http://127.0.0.1:8501")
        return
    outputs = json.loads(
        subprocess.check_output(
            ["terraform", "-chdir=" + str(ROOT / "terraform"), "output", "-json"],
            text=True,
        )
    )
    bastion = outputs.get("bastion_name", {}).get("value")
    bastion_pid = None
    target = address
    port = "22"
    if bastion:
        log_path = ACCESS / "bastion.log"
        fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as log:
            process = subprocess.Popen(
                [
                    "az",
                    "network",
                    "bastion",
                    "tunnel",
                    "--name",
                    bastion,
                    "--resource-group",
                    "rg-fx-warehouse-dev",
                    "--target-resource-id",
                    outputs["windows_vm_id"]["value"],
                    "--resource-port",
                    "22",
                    "--port",
                    "2222",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        bastion_pid = process.pid
        state_path.write_text(
            json.dumps({"address": address, "bastion_pid": bastion_pid})
        )
        os.chmod(state_path, 0o600)
        for _ in range(60):
            if process.poll() is not None:
                raise SystemExit("Bastion tunnel failed; see data/access/bastion.log")
            try:
                with network_socket.create_connection(("127.0.0.1", 2222), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)
        else:
            process.terminate()
            raise SystemExit("Bastion tunnel did not become ready")
        target, port = "127.0.0.1", "2222"
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    with (
        DefaultAzureCredential() as credential,
        BlobServiceClient(
            "https://stfx36c63c6a50e8.blob.core.windows.net/", credential
        ) as service,
    ):
        evidence = json.loads(
            service.get_blob_client("fx-data", "access/ssh-host.json")
            .download_blob()
            .readall()
            .decode("utf-8-sig")
        )
    parts = evidence["host_public_key"].split()
    if len(parts) < 2 or parts[0] != "ssh-ed25519":
        raise SystemExit("Unexpected SSH host-key evidence")
    known = ACCESS / "known_hosts"
    known.write_text(f"{address} {parts[0]} {parts[1]}\n")
    os.chmod(known, 0o600)
    if socket.exists():
        socket.unlink()
    subprocess.run(
        [
            "ssh",
            "-f",
            "-N",
            "-M",
            "-S",
            str(socket),
            "-p",
            port,
            "-o",
            "HostKeyAlias=" + address,
            "-i",
            str(key),
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "UserKnownHostsFile=" + str(known),
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-L",
            "127.0.0.1:8501:127.0.0.1:8501",
            f"fxadmin@{target}",
        ],
        check=True,
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8501/_stcore/health", timeout=3
            ) as response:
                if response.read().strip() != b"ok":
                    raise RuntimeError("Unexpected dashboard health response")
            break
        except OSError:
            if attempt == 4:
                raise RuntimeError(
                    "SSH connected but dashboard health check failed"
                ) from None
            time.sleep(0.5)
    state_path.write_text(
        json.dumps(
            {
                "address": target,
                "bastion_pid": bastion_pid,
                "local_url": "http://127.0.0.1:8501",
            }
        )
    )
    print("Dashboard available: http://127.0.0.1:8501")


if __name__ == "__main__":
    main()
