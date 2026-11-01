"""Prepare a traceable rate batch and SQL input for the SSIS file connection."""

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from uuid import uuid4

from pipeline.common import sql_literal, verified_bytes
from pipeline.prepare_rates import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--code-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    payload = verified_bytes(args.archive, manifest["sha256"], manifest["bytes"])
    rows = prepare(payload, args.start, args.end)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "fx_rates.csv").open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    run_id = str(uuid4())
    parameters = {
        "run_id": run_id,
        "source_sha256": manifest["sha256"],
        "source_url": manifest["source_url"],
        "blob_path": f"raw/ecb/{manifest['sha256']}/eurofxref-hist.zip",
        "retrieved_at": manifest["retrieved_at"],
        "byte_count": manifest["bytes"],
        "code_version": args.code_version,
        "payload": json.dumps(rows, separators=(",", ":")),
    }
    statement = (
        "EXEC warehouse.LoadRates\n"
        + ",\n".join(
            f"    @{key} = {sql_literal(value)}" for key, value in parameters.items()
        )
        + ";\n"
    )
    (args.output / "current-rate-load.sql").write_text(statement, encoding="utf-8-sig")
    (args.output / "batch.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "rows": len(rows),
                "source_sha256": manifest["sha256"],
                "start": args.start.isoformat(),
                "end": args.end.isoformat(),
                "code_version": args.code_version,
            },
            indent=2,
        )
    )
    print(f"Prepared {len(rows)} rates, run {run_id}")


if __name__ == "__main__":
    main()
