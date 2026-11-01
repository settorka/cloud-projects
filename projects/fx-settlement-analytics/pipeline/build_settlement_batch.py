"""Verify generated files and build input for the settlement SSIS package."""

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pipeline.common import sql_literal, verified_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--code-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = (args.source / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    for name in ("trades.csv", "payments.csv", "expected.json"):
        metadata = manifest["files"][name]
        verified_bytes(args.source / name, metadata["sha256"], metadata["bytes"])
    parameters = {
        "batch_id": hashlib.sha256(raw).hexdigest(),
        "run_id": str(uuid4()),
        "code_version": args.code_version,
        "manifest": raw.decode(),
        "retrieved_at": datetime.now(UTC).isoformat(),
    }
    for entity in ("trades", "payments"):
        with (args.source / f"{entity}.csv").open() as source:
            parameters[entity] = json.dumps(
                list(csv.DictReader(source)), separators=(",", ":")
            )
    args.output.mkdir(parents=True, exist_ok=True)
    statement = (
        "EXEC warehouse.LoadSettlements\n"
        + ",\n".join(
            f"    @{key} = {sql_literal(value)}" for key, value in parameters.items()
        )
        + ";\n"
    )
    (args.output / "current-settlement-load.sql").write_text(
        statement, encoding="utf-8-sig"
    )
    (args.output / "settlement-batch.json").write_text(
        json.dumps(
            {
                "batch_id": parameters["batch_id"],
                "run_id": parameters["run_id"],
                "code_version": args.code_version,
                "as_of_date": manifest["as_of_date"],
                "trades": manifest["trade_count"],
                "payments": manifest["payment_count"],
            },
            indent=2,
        )
    )
    print(f"Prepared synthetic batch {parameters['batch_id']}")


if __name__ == "__main__":
    main()
