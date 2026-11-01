"""Prepare same-date rates without filling missing ECB observations."""

import argparse
import csv
import hashlib
import io
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

from pipeline.download_ecb import validate_archive


def prepare(payload: bytes, start: date, end: date) -> list[dict]:
    if start > end:
        raise ValueError("Start date must not follow end date")
    source_hash = hashlib.sha256(payload).hexdigest()
    reader = csv.DictReader(io.StringIO(validate_archive(payload).decode("utf-8-sig")))
    if not {"Date", "USD", "GBP"}.issubset(reader.fieldnames or []):
        raise ValueError("ECB CSV requires Date, USD and GBP columns")
    result, seen = [], set()
    for line, row in enumerate(reader, start=2):
        day = date.fromisoformat(row["Date"].strip())
        if not start <= day <= end:
            continue
        if day in seen:
            raise ValueError(f"Duplicate observation date: {day}")
        seen.add(day)
        observations = {}
        for currency in ("USD", "GBP"):
            text = row[currency].strip()
            if text in ("", "N/A"):
                continue
            try:
                rate = Decimal(text)
            except InvalidOperation as exc:
                raise ValueError(f"Invalid {currency} observation on {day}") from exc
            if not rate.is_finite() or rate <= 0:
                raise ValueError(
                    f"Nonpositive/nonfinite {currency} observation on {day}"
                )
            observations[currency] = rate
        pairs = [(f"EUR/{ccy}", value, ccy) for ccy, value in observations.items()]
        if len(observations) == 2:
            with localcontext() as context:
                context.prec = 28
                cross = observations["USD"] / observations["GBP"]
            pairs.append(("GBP/USD", cross, "USD+GBP"))
        for pair, value, inputs in pairs:
            result.append(
                {
                    "rate_date": day.isoformat(),
                    "pair": pair,
                    "rate": str(value),
                    "classification": "derived" if pair == "GBP/USD" else "observed",
                    "source_sha256": source_hash,
                    "source_row": line,
                    "input_currencies": inputs,
                }
            )
    if not result:
        raise ValueError("No usable observations in requested date range")
    return sorted(result, key=lambda row: (row["rate_date"], row["pair"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = prepare(args.archive.read_bytes(), args.start, args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Prepared {len(rows)} rates")


if __name__ == "__main__":
    main()
