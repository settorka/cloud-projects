"""Canonical V2 environment loading for workstation tools."""

import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def load_environment(filename=None):
    path = Path(filename or os.getenv("V2_ENV_FILE", ROOT / "v2.env")).resolve()
    if not path.is_file():
        raise RuntimeError(f"Configuration missing: {path}; copy v2.env.example to v2.env")
    load_dotenv(path, override=False)
    os.environ["V2_ENV_FILE"] = str(path)
    return path
