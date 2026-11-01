"""Opt-in live Azure tests; only delete objects created by this test."""

import hashlib
import io
import json
import os
import uuid
import zipfile

import pytest

from pipeline.download_ecb import URL, upload

pytestmark = pytest.mark.skipif(
    os.environ.get("FX_LIVE_AZURE") != "1",
    reason="Set FX_LIVE_AZURE=1 for real Blob tests",
)


def test_partial_upload_recovers_and_replay_preserves_commit(tmp_path):
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("eurofxref-hist.csv", "Date,USD,GBP\n2025-01-02,1.25,0.80\n")
        archive.writestr("test-id.txt", str(uuid.uuid4()))
    payload = buffer.getvalue()
    manifest = {
        "source_url": URL,
        "retrieved_at": "2025-01-03T00:00:00+00:00",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "classification": "observed_reference_rates",
    }
    (tmp_path / "eurofxref-hist.zip").write_bytes(payload)
    prefix = f"raw/ecb/{manifest['sha256']}"
    with (
        DefaultAzureCredential() as credential,
        BlobServiceClient(
            os.environ["AZURE_STORAGE_ACCOUNT_URL"], credential
        ) as service,
    ):
        container = service.get_container_client(os.environ["AZURE_STORAGE_CONTAINER"])
        raw = container.get_blob_client(f"{prefix}/eurofxref-hist.zip")
        commit = container.get_blob_client(f"{prefix}/manifest.json")
        try:
            raw.upload_blob(
                payload, overwrite=False
            )  # Simulate interrupted publication.
            assert not commit.exists()
            assert upload(tmp_path, manifest) == prefix
            first_etag = commit.get_blob_properties().etag
            replay = {**manifest, "retrieved_at": "2025-01-04T00:00:00+00:00"}
            assert upload(tmp_path, replay) == prefix
            assert replay["retrieved_at"] == manifest["retrieved_at"]
            assert commit.get_blob_properties().etag == first_etag
            assert raw.download_blob().readall() == payload
            assert (
                json.loads(commit.download_blob().readall())["sha256"]
                == manifest["sha256"]
            )
            (tmp_path / "eurofxref-hist.zip").write_bytes(b"changed")
            with pytest.raises(ValueError, match="does not match"):
                upload(tmp_path, manifest)
        finally:
            if commit.exists():
                commit.delete_blob()
            if raw.exists():
                raw.delete_blob()
