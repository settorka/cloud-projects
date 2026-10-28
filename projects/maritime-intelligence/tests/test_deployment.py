"""Deployment safety and artifact contracts without creating AWS resources."""

import importlib.util
import json
import shutil
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deployment_role_cannot_modify_iam_or_delete_state():
    config = tool("aws_bootstrap").policies("123456789012", "eu-west-2", "maritime-intelligence")
    statements = config["deployment"]["Statement"]
    iam_actions = {a for s in statements for a in s["Action"] if a.startswith("iam:")}
    assert iam_actions == {"iam:GetRole", "iam:GetInstanceProfile", "iam:PassRole"}
    passage = next(s for s in statements if "iam:PassRole" in s["Action"])
    assert len(passage["Resource"]) == 3
    assert all("GitHubActionsDevRole" not in arn for arn in passage["Resource"])
    deletion = next(
        s for s in statements if "s3:DeleteObject" in s["Action"] and "tflock" in str(s["Resource"])
    )
    assert deletion["Resource"].endswith(".tflock")
    assert len(json.dumps(config["deployment"], separators=(",", ":"))) < 10240


def plan(kind, after=None, actions=None):
    return {
        "resource_changes": [
            {
                "mode": "managed",
                "address": kind + ".test",
                "type": kind,
                "change": {"actions": actions or ["create"], "after": after or {}},
            }
        ]
    }


@pytest.mark.parametrize(
    "case",
    [
        plan("aws_instance", actions=["delete", "create"]),
        plan("aws_iam_role"),
        plan("aws_nat_gateway"),
        plan("aws_instance", {"instance_type": "m7i.4xlarge"}),
        plan("aws_security_group", {"ingress": [{"from_port": 5432, "to_port": 5432}]}),
    ],
)
def test_plan_guard_rejects_destructive_expensive_or_public_database_changes(case):
    with pytest.raises(ValueError):
        tool("check_plan").check(case)


def test_rollout_input_is_content_addressed_and_shell_quoted():
    deploy = tool("deploy")
    with pytest.raises(ValueError):
        deploy.rollout_commands({"bucket": "safe", "region": "eu-west-2"}, "artifacts/../../wrong")
    commands = deploy.rollout_commands(
        {"bucket": "safe", "region": "eu-west-2"}, "artifacts/" + "a" * 64 + ".tar.gz"
    )
    assert "cloud-init status --wait" in commands[0]
    assert "deployment.json" in commands[0]
    assert "API_TOKEN" not in commands[0]


def test_release_is_reproducible_and_excludes_local_secrets(tmp_path):
    shutil.copytree(ROOT / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "migrations", tmp_path / "migrations")
    for name in [
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
    ]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    text = (
        (ROOT / ".env.example")
        .read_text()
        .replace(
            "API_TOKEN=local-only-replace-with-a-random-token",
            "API_TOKEN=private-token-do-not-package",
        )
        .replace(
            "POSTGRES_PASSWORD=local-maritime-development",
            "POSTGRES_PASSWORD=private-password-do-not-package",
        )
    )
    (tmp_path / ".env").write_text(text)
    builder = tool("package_release")
    first = builder.build(tmp_path)
    second = builder.build(tmp_path)
    assert first == second
    with tarfile.open(tmp_path / "dist/application.tar.gz") as archive:
        assert ".env" not in archive.getnames()
        for member in archive.getmembers():
            content = archive.extractfile(member).read()
            assert b"private-token-do-not-package" not in content
            assert b"private-password-do-not-package" not in content
        runtime = json.load(archive.extractfile("deploy/v2/runtime.json"))
        assert "API_TOKEN" not in runtime and "DATABASE_URL" not in runtime
    with zipfile.ZipFile(tmp_path / "dist/references-lambda.zip") as archive:
        assert "v2/lambda_handlers.py" in archive.namelist()
        assert "v1/api.py" not in archive.namelist()
    (tmp_path / ".env").write_text(
        text.replace("private-token-do-not-package", "a-different-private-token")
    )
    assert builder.build(tmp_path) == first


def test_host_config_preserves_secrets_and_uses_aws_adapters(tmp_path):
    from dotenv import dotenv_values

    base = tmp_path / "host"
    release = base / "releases" / ("a" * 64)
    (release / "deploy/v2").mkdir(parents=True)
    shutil.copy2(ROOT / ".env.example", release / ".env.example")
    config = dotenv_values(ROOT / ".env.example")
    config = {k: v for k, v in config.items() if k not in tool("package_release").SECRET_KEYS}
    config["DIGITRAFFIC_USER"] = "trader's-research"
    (release / "deploy/v2/runtime.json").write_text(json.dumps(config))
    (base / "deployment.json").write_text(
        json.dumps(
            {
                "bucket": "aws-private-bucket",
                "region": "eu-west-2",
                "domain": "",
                "bbox": "19,59,30,66",
                "tunnel_port": 8200,
                "project": "maritime-intelligence",
            }
        )
    )
    renderer = tool("configure_host")
    renderer.configure(base, release)
    first = dotenv_values(base / ".env")
    renderer.configure(base, release)
    second = dotenv_values(base / ".env")
    assert second["API_TOKEN"] == first["API_TOKEN"]
    assert second["POSTGRES_PASSWORD"] == first["POSTGRES_PASSWORD"]
    assert second["DIGITRAFFIC_USER"] == "trader's-research"
    assert second["S3_ENDPOINT_URL"] == "" and second["AWS_ACCESS_KEY_ID"] == ""
    assert second["API_BIND"] == "127.0.0.1:8200" and second["COMPOSE_PROFILES"] == ""
    assert first["POSTGRES_PASSWORD"] in second["DATABASE_URL"]
    config["POSTGRES_DB"] = "a-different-database"
    (release / "deploy/v2/runtime.json").write_text(json.dumps(config))
    with pytest.raises(ValueError, match="explicit data migration"):
        renderer.configure(base, release)
    assert dotenv_values(base / ".env")["POSTGRES_DB"] == first["POSTGRES_DB"]


def test_generated_ssm_script_is_valid_bash_and_checks_hash_before_extracting():
    import subprocess

    commands = tool("deploy").rollout_commands(
        {"bucket": "safe", "region": "eu-west-2"}, "artifacts/" + "a" * 64 + ".tar.gz"
    )[0]
    subprocess.run(["bash", "-n"], input=commands, text=True, check=True)
    assert commands.index("sha256sum -c") < commands.index("tar -xzf")


def test_plan_guard_accepts_budgeted_encrypted_host():
    tool("check_plan").check(
        plan(
            "aws_instance",
            {
                "instance_type": "t3a.large",
                "root_block_device": [{"volume_size": 100, "encrypted": True}],
                "metadata_options": [{"http_tokens": "required"}],
                "credit_specification": [{"cpu_credits": "standard"}],
            },
        )
    )
