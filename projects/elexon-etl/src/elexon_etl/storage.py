"""The pipeline needs object reads/writes and one renewable partition lock."""

import fcntl
import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class LocalStore:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def _path(self, key):
        target = (self.root / key).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("Storage path escapes root")
        return target

    def get(self, key, destination):
        import shutil

        path = self._path(key)
        if not path.is_file():
            return False
        shutil.copyfile(path, destination)
        return True

    def put(self, key, source):
        import shutil

        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def lock(self, partition):
        path = self._path(f"metadata/{partition}/lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield lambda: None

    def close(self):
        pass

    def list_objects(self, prefix):
        for path in self._path(prefix).rglob("*"):
            if path.is_file():
                yield (
                    str(path.relative_to(self.root)),
                    datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
                )

    def delete(self, key):
        self._path(key).unlink()


class AzureStore:
    def __init__(self, account, client_id=None):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        self.credential = DefaultAzureCredential(managed_identity_client_id=client_id)
        self.service = BlobServiceClient(
            f"https://{account}.blob.core.windows.net", credential=self.credential
        )
        self.leases = {}

    def _blob(self, key):
        container, name = key.split("/", 1)
        if container not in {"raw", "curated", "metadata"}:
            raise ValueError("Unknown container")
        return self.service.get_blob_client(container, name)

    def get(self, key, destination):
        from azure.core.exceptions import ResourceNotFoundError

        try:
            with Path(destination).open("wb") as output:
                self._blob(key).download_blob(max_concurrency=1).readinto(output)
            return True
        except ResourceNotFoundError:
            return False

    def put(self, key, source):
        with Path(source).open("rb") as data:
            self._blob(key).upload_blob(
                data, overwrite=True, max_concurrency=1, lease=self.leases.get(key)
            )

    @contextmanager
    def lock(self, partition):
        from azure.core.exceptions import HttpResponseError, ResourceExistsError

        # Lease the publication pointer itself: Azure rejects a stale owner's publish,
        # even if its process was suspended past lease expiry after its last check.
        key = f"metadata/{partition}/complete.json"
        blob = self._blob(key)
        try:
            blob.upload_blob(b"{}", overwrite=False)
        except ResourceExistsError:
            pass
        except HttpResponseError as exc:
            # Azure checks a live lease before If-None-Match on a create-only upload.
            if getattr(exc, "error_code", None) in {"LeaseIdMissing", "LeaseAlreadyPresent"}:
                raise BlockingIOError("Partition already has a writer") from exc
            raise
        try:
            lease = blob.acquire_lease(lease_duration=60)
        except HttpResponseError as exc:
            if getattr(exc, "error_code", None) == "LeaseAlreadyPresent":
                raise BlockingIOError("Partition already has a writer") from exc
            raise
        self.leases[key] = lease
        stop = threading.Event()
        errors = []

        def renew():
            while not stop.wait(15):
                try:
                    lease.renew()
                except Exception as exc:
                    errors.append(exc)
                    return

        def check():
            if errors:
                raise RuntimeError("Partition lease lost; refusing to publish") from errors[0]
            # Confirm ownership synchronously at each state write, especially publication.
            lease.renew()

        worker = threading.Thread(target=renew, daemon=True)
        worker.start()
        try:
            yield check
        finally:
            stop.set()
            worker.join(timeout=20)
            self.leases.pop(key, None)
            try:
                lease.release()
            except Exception:
                if not errors:
                    raise

    def close(self):
        self.service.close()
        self.credential.close()

    def list_objects(self, prefix):
        container, name = prefix.split("/", 1)
        for blob in self.service.get_container_client(container).list_blobs(name_starts_with=name):
            yield f"{container}/{blob.name}", blob.last_modified

    def delete(self, key):
        self._blob(key).delete_blob()


def load_json(store, key, workspace):
    path = workspace / "read-manifest.json"
    return json.loads(path.read_text()) if store.get(key, path) else None


def save_json(store, key, value, workspace):
    path = workspace / "write-manifest.json"
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    store.put(key, path)
