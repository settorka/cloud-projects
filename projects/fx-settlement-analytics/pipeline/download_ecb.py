"""Download a bounded ECB archive and publish an immutable Blob batch."""

import argparse
import hashlib
import io
import json
import os
import ssl
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
MAX_BYTES = 20 * 1024 * 1024


def validate_archive(payload: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        info = archive.getinfo("eurofxref-hist.csv")
        if info.file_size > MAX_BYTES:
            raise ValueError("Expanded ECB CSV exceeds size limit")
        return archive.read(info)


def download(output: Path) -> dict:
    import certifi

    request = urllib.request.Request(
        URL, headers={"User-Agent": "fx-settlement-analytics/0.1"}
    )
    with urllib.request.urlopen(
        request, timeout=60, context=ssl.create_default_context(cafile=certifi.where())
    ) as response:
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("ECB archive exceeds size limit")
    validate_archive(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    (output / "eurofxref-hist.zip").write_bytes(payload)
    manifest = {
        "source_url": URL,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "sha256": checksum,
        "bytes": len(payload),
        "classification": "observed_reference_rates",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def upload(output: Path, manifest: dict) -> str:
    from azure.core.exceptions import ResourceExistsError
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    payload = (output / "eurofxref-hist.zip").read_bytes()
    if hashlib.sha256(payload).hexdigest() != manifest["sha256"]:
        raise ValueError("Local archive does not match manifest")
    if len(payload) != manifest["bytes"]:
        raise ValueError("Local archive size does not match manifest")
    prefix = "raw/ecb/" + manifest["sha256"]
    with (
        DefaultAzureCredential() as credential,
        BlobServiceClient(
            os.environ["AZURE_STORAGE_ACCOUNT_URL"], credential
        ) as service,
    ):
        container = service.get_container_client(os.environ["AZURE_STORAGE_CONTAINER"])
        # Create-only writes; verify existing bytes when replaying or recovering.
        blob = container.get_blob_client(f"{prefix}/eurofxref-hist.zip")
        try:
            blob.upload_blob(payload, overwrite=False)
        except ResourceExistsError:
            if blob.download_blob().readall() != payload:
                raise ValueError(
                    "Existing raw blob differs from local archive"
                ) from None
        commit = container.get_blob_client(f"{prefix}/manifest.json")
        try:
            commit.upload_blob(json.dumps(manifest, indent=2) + "\n", overwrite=False)
        except ResourceExistsError:
            existing = json.loads(commit.download_blob().readall())
            for key in ("source_url", "sha256", "bytes", "classification"):
                if existing.get(key) != manifest[key]:
                    raise ValueError(f"Existing manifest differs on {key}") from None
            # Preserve the first successful retrieval as canonical batch metadata.
            manifest.update(existing)
    return prefix


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()
    manifest = download(args.output)
    if args.upload:
        manifest["blob_prefix"] = upload(args.output, manifest)
        (args.output / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
