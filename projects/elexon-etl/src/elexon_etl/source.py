"""Read only PN/BOD archive filenames; dates are UTC publication-file dates."""

import hashlib
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree

import httpx

ARCHIVE = "https://archive.data.elexon.co.uk/iris-archive"
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_PARTITION_BYTES = 512 * 1024 * 1024
MAX_FILES = 1000


@dataclass(frozen=True)
class SourceFile:
    name: str
    size: int
    etag: str


class Archive:
    def __init__(self, client=None, sleep=time.sleep):
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(60, connect=10), follow_redirects=False
        )
        self.sleep = sleep

    def _retry(self, operation):
        for attempt in range(3):
            try:
                return operation()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 429 and exc.response.status_code < 500:
                    raise
                if attempt == 2:
                    raise
            except httpx.TransportError:
                if attempt == 2:
                    raise
            self.sleep(2**attempt)

    def discover(self, dataset: str, day: date):
        if dataset not in {"PN", "BOD"}:
            raise ValueError("Only PN and BOD filename discovery is supported")
        prefix = f"data/{dataset}/{dataset}_{day:%Y%m%d}"
        marker = None
        seen_markers = set()
        files = {}
        for _ in range(10):
            params = {"restype": "container", "comp": "list", "prefix": prefix, "maxresults": 1000}
            if marker:
                params["marker"] = marker

            def request():
                response = self.client.get(ARCHIVE, params=params)
                response.raise_for_status()
                if len(response.content) > 4 * 1024 * 1024:
                    raise ValueError("Oversized archive listing")
                return ElementTree.fromstring(response.content)

            root = self._retry(request)
            for blob in root.findall("./Blobs/Blob"):
                name = blob.findtext("Name", "")
                if not name.startswith(prefix) or not name.endswith(".json"):
                    raise ValueError("Unexpected archive filename")
                item = SourceFile(
                    name,
                    int(blob.findtext("./Properties/Content-Length", "-1")),
                    blob.findtext("./Properties/Etag", ""),
                )
                if not 0 < item.size <= MAX_FILE_BYTES or not item.etag:
                    raise ValueError("Missing ETag or source file exceeds size limit")
                if name in files and files[name] != item:
                    raise ValueError("Archive changed during discovery; rerun")
                files[name] = item
            if len(files) > MAX_FILES or sum(f.size for f in files.values()) > MAX_PARTITION_BYTES:
                raise ValueError("Partition exceeds file/byte safety limits")
            marker = root.findtext("NextMarker")
            if not marker:
                break
            if marker in seen_markers:
                raise ValueError("Repeated archive pagination marker")
            seen_markers.add(marker)
        else:
            raise ValueError("Archive listing pagination limit exceeded")
        if not files:
            raise ValueError("No source files found; partition cannot be complete")
        return sorted(files.values(), key=lambda f: f.name)

    def download(self, source: SourceFile, destination: Path):
        def request():
            digest = hashlib.sha256()
            size = 0
            # The archive CDN rejects conditional GETs. Compare the returned revision before
            # consuming its body instead; a changed source requires rediscovery.
            with self.client.stream(
                "GET",
                f"{ARCHIVE}/{quote(source.name, safe='/')}",
                headers={"Accept-Encoding": "identity"},
            ) as response:
                response.raise_for_status()
                if response.headers.get("etag", "").strip('"') != source.etag.strip('"'):
                    raise ValueError("Source revision changed; rediscover before retrying")
                with destination.open("wb") as output:
                    for chunk in response.iter_bytes(65536):
                        size += len(chunk)
                        if size > MAX_FILE_BYTES:
                            raise ValueError("Source download exceeds byte limit")
                        digest.update(chunk)
                        output.write(chunk)
            if size != source.size:
                raise ValueError("Source size changed; rediscover before retrying")
            return digest.hexdigest()

        return self._retry(request)

    def close(self):
        self.client.close()
