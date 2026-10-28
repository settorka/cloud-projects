"""Render the host's grouped environment without executing configuration as shell."""

import json
import secrets
import sys
from pathlib import Path


def configure(base, release):
    deployment = json.loads((base / "deployment.json").read_text())
    config = json.loads((release / "deploy/v2/runtime.json").read_text())
    old = {}
    if (base / ".env").exists():
        for line in (base / ".env").read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if value.startswith("'") and value.endswith("'"):
                    value = value[1:-1].replace("\\'", "'").replace("\\\\", "\\")
                elif value.startswith('"') and value.endswith('"'):
                    value = json.loads(value)
                old[key] = value
        for key in ["POSTGRES_USER", "POSTGRES_DB", "KAFKA_CLUSTER_ID"]:
            if old.get(key) and config.get(key) != old[key]:
                raise ValueError(key + " changes require an explicit data migration")
    config.update(
        {
            "COMPOSE_PROJECT_NAME": "maritime-v2",
            "APP_IMAGE": "maritime-intelligence:" + release.name,
            "POSTGRES_PASSWORD": old.get("POSTGRES_PASSWORD", secrets.token_hex(24)),
            "API_TOKEN": old.get("API_TOKEN", secrets.token_hex(32)),
            "S3_BUCKET": deployment["bucket"],
            "S3_ENDPOINT_URL": "",
            "S3_PATH_STYLE": "false",
            "AWS_DEFAULT_REGION": deployment["region"],
            "AWS_ACCESS_KEY_ID": "",
            "AWS_SECRET_ACCESS_KEY": "",
            "AIS_BBOX": deployment["bbox"],
            "API_BIND": "127.0.0.1:" + str(deployment["tunnel_port"]),
            "DOMAIN": deployment["domain"],
            "COMPOSE_PROFILES": "public" if deployment["domain"] else "",
            "OTEL_DEPLOYMENT_ENVIRONMENT": "aws",
            "OTEL_PROJECT_NAME": deployment["project"],
            "CLOUDWATCH_LOG_GROUP": "/" + deployment["project"] + "/application",
            "CLOUDWATCH_METRICS_LOG_GROUP": "/" + deployment["project"] + "/metrics",
        }
    )
    lines = []
    for line in (release / ".env.example").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key = line.split("=", 1)[0]
            if key in config:
                value = str(config[key])
                if "\n" in value or "\r" in value:
                    raise ValueError("Configuration contains a newline")
                # Compose/dotenv single quotes keep dollar signs and backticks literal.
                # DATABASE_URL is intentionally absent from config and keeps template expansion.
                line = key + "=" + "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
        lines.append(line)
    path = base / ".env"
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)
    link = release / ".env"
    if link.is_symlink():
        link.unlink()
    link.symlink_to(path)


if __name__ == "__main__":
    configure(Path(sys.argv[1]), Path(sys.argv[2]))
