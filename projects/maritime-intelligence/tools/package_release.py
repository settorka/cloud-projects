"""Build deterministic, secret-free host and Lambda releases."""

import gzip
import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
SECRET_KEYS = {
    "API_TOKEN",
    "POSTGRES_PASSWORD",
    "DATABASE_URL",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "ENV_FILE",
}


def build(root=ROOT):
    output = root / "dist"
    output.mkdir(exist_ok=True)
    template = dotenv_values(root / ".env.example")
    local = dotenv_values(root / ".env") if (root / ".env").is_file() else template
    # Only known non-secret configuration crosses the deployment boundary.
    config = {
        key: local.get(key, value) for key, value in template.items() if key not in SECRET_KEYS
    }
    seconds = int(config["REFERENCE_INTERVAL_SECONDS"])
    if seconds < 60 or seconds % 60:
        raise ValueError("AWS reference interval must be whole minutes >=60")
    reference = {
        key: config[key]
        for key in [
            "REFERENCE_API_URL",
            "REFERENCE_INTERVAL_SECONDS",
            "REFERENCE_MAX_BYTES",
            "HTTP_TIMEOUT_SECONDS",
            "DIGITRAFFIC_USER",
            "S3_MAX_ATTEMPTS",
        ]
    }
    reference.update(S3_ENDPOINT_URL="", S3_PATH_STYLE="false")
    (output / "reference-environment.json").write_text(json.dumps(reference, sort_keys=True))
    paths = [
        root / p
        for p in [
            "src",
            "migrations",
            "deploy/v2/compose.yaml",
            "Dockerfile",
            ".dockerignore",
            ".env.example",
            "pyproject.toml",
            "uv.lock",
            "tools/backup.sh",
            "tools/rollout.sh",
            "tools/restore_check.sh",
            "deploy/v2/otel-collector.yaml",
            "tools/configure_host.py",
        ]
    ]
    files = {}
    for path in paths:
        for item in sorted(path.rglob("*")) if path.is_dir() else [path]:
            if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc":
                files[str(item.relative_to(root))] = item.read_bytes()
    files["deploy/v2/runtime.json"] = json.dumps(config, sort_keys=True).encode()
    with (output / "application.tar.gz").open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for name, body in sorted(files.items()):
                    info = tarfile.TarInfo(name)
                    info.size = len(body)
                    info.mode = 0o755 if name.endswith(".sh") else 0o644
                    archive.addfile(info, io.BytesIO(body))
    # Lambda needs only these pure-Python modules plus the runtime's boto3.
    modules = [
        "v1/__init__.py",
        "v1/adapters/__init__.py",
        "v1/adapters/references.py",
        "v1/adapters/s3.py",
        "v1/settings.py",
        "v1/visits.py",
        "v1/services.py",
        "v2/__init__.py",
        "v2/lambda_handlers.py",
    ]
    with zipfile.ZipFile(output / "references-lambda.zip", "w") as archive:
        for name in sorted(modules):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (root / "src" / name).read_bytes())
    return hashlib.sha256((output / "application.tar.gz").read_bytes()).hexdigest()


if __name__ == "__main__":
    print("Built release", build())
