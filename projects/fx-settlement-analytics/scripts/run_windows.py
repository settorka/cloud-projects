"""Publish an explicit, checksummed source bundle and run it on the dev VM."""

import argparse
import hashlib
import io
import json
import re
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

ACCOUNT = "https://stfx36c63c6a50e8.blob.core.windows.net/"
CONTAINER = "fx-data"


def bundle(assets):
    files = {}
    for remote, local in assets:
        path = PurePosixPath(remote)
        if path.is_absolute() or ".." in path.parts or any(c in remote for c in "'\\:"):
            raise ValueError("Asset destination must be a safe relative path")
        name = str(path)
        if name in files:
            raise ValueError(f"Duplicate asset destination: {name}")
        files[name] = local.read_bytes()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in sorted(files.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return output.getvalue()


def publish(payload):
    from azure.core.exceptions import ResourceExistsError
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    checksum = hashlib.sha256(payload).hexdigest()
    name = f"deploy/bundles/{checksum}.zip"
    with (
        DefaultAzureCredential() as credential,
        BlobServiceClient(ACCOUNT, credential) as service,
    ):
        blob = service.get_blob_client(CONTAINER, name)
        try:
            blob.upload_blob(payload, overwrite=False)
        except ResourceExistsError:
            if hashlib.sha256(blob.download_blob().readall()).hexdigest() != checksum:
                raise ValueError(
                    "Existing deployment bundle checksum differs"
                ) from None
    return checksum, ACCOUNT + CONTAINER + "/" + name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    parser.add_argument(
        "--asset", action="append", default=[], help="relative-remote-path=local-path"
    )
    parser.add_argument(
        "--parameter", action="append", default=[], help="PowerShell-parameter=value"
    )
    args = parser.parse_args()
    assets = [("scripts/" + args.script.name, args.script)]
    for item in args.asset:
        remote, local = item.split("=", 1)
        assets.append((remote, Path(local)))
    parameters = []
    for item in args.parameter:
        name, value = item.split("=", 1)
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            parser.error("Invalid PowerShell parameter name")
        escaped = value.replace("'", "''")
        parameters.append(f"'{name}' = '{escaped}'")
    payload = bundle(assets)
    checksum, url = publish(payload)
    # Only a small bootstrap script crosses Run Command; large lockfiles stay in Blob.
    remote_script = f"""
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
New-Item -ItemType Directory -Force -Path 'F:\\fx\\deploy','F:\\fx\\app' | Out-Null
$token=Invoke-RestMethod -Headers @{{Metadata='true'}} -Uri 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fstorage.azure.com%2F'
$headers=@{{Authorization="Bearer $($token.access_token)";'x-ms-version'='2023-11-03'}}
$zip='F:\\fx\\deploy\\{checksum}.zip'
Invoke-WebRequest '{url}' -Headers $headers -OutFile $zip -UseBasicParsing -TimeoutSec 60
if((Get-FileHash $zip -Algorithm SHA256).Hash.ToLower() -ne '{checksum}') {{throw 'Deployment bundle checksum mismatch.'}}
$stage='F:\\fx\\deploy\\{checksum}'
if(Test-Path $stage) {{Remove-Item $stage -Recurse -Force}}
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::ExtractToDirectory($zip,$stage)
Copy-Item "$stage\\*" 'F:\\fx\\app' -Recurse -Force
$env:FX_CODE_VERSION='{checksum}'
$fxParameters=@{{{";".join(parameters)}}}
& 'F:\\fx\\app\\scripts\\{args.script.name}' @fxParameters
Write-Output 'FX_WINDOWS_SUCCESS'
"""
    result = subprocess.run(
        [
            "az",
            "vm",
            "run-command",
            "invoke",
            "-g",
            "rg-fx-warehouse-dev",
            "-n",
            "vm-fx-dev",
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
    output = "\n".join(
        item.get("message", "") for item in json.loads(result.stdout)["value"]
    )
    print(output)
    if "FX_WINDOWS_SUCCESS" not in output.splitlines():
        raise SystemExit("Windows execution failed: success marker absent")


if __name__ == "__main__":
    main()
