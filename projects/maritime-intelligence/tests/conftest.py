from pathlib import Path

import pytest
from dotenv import dotenv_values

from v1.settings import Settings


@pytest.fixture
def settings(monkeypatch):
    # Tests use declared example configuration, never a developer's local secrets.
    root = Path(__file__).resolve().parents[1]
    for key, value in dotenv_values(root / ".env.example").items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("ENV_FILE", str(root / "tests" / "nonexistent.env"))
    return Settings.load()
