"""Shared file-integrity and SQL input helpers; no cloud or database dependencies."""

import hashlib
from pathlib import Path


def verified_bytes(path: Path, expected_hash: str, expected_size: int) -> bytes:
    payload = path.read_bytes()
    if len(payload) != expected_size:
        raise ValueError(f"{path.name} byte count differs from manifest")
    if hashlib.sha256(payload).hexdigest() != expected_hash:
        raise ValueError(f"{path.name} hash differs from manifest")
    return payload


def sql_literal(value) -> str:
    return "N'" + str(value).replace("'", "''") + "'"
