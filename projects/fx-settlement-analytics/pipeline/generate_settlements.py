"""Deterministic synthetic gross settlements anchored to observed ECB dates/rates."""

import argparse
import csv
import hashlib
import json
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

SCENARIOS = (
    "exact",
    "split",
    "partial",
    "missing",
    "duplicate",
    "wrong_currency",
    "late",
    "overpaid",
)
CENT = Decimal("0.01")


def money(value):
    return str(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


def business_days(day, count):
    while count:
        day += timedelta(days=1)
        if day.weekday() < 5:
            count -= 1
    return day


def write_csv(path, rows):
    with path.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def generate(rates_path: Path, output: Path, count=1000, seed=42):
    if not -(2**31) <= seed < 2**31:
        raise ValueError("Seed must fit a SQL Server int")
    if not 8 <= count <= 100_000:
        raise ValueError("Trade count must be between 8 and 100000")
    with rates_path.open() as source:
        rates = sorted(
            csv.DictReader(source), key=lambda r: (r["rate_date"], r["pair"])
        )
    if not rates or len({r["source_sha256"] for r in rates}) != 1:
        raise ValueError("Use one nonempty ECB source snapshot")
    for row in rates:
        if (
            row["pair"] not in ("EUR/USD", "EUR/GBP", "GBP/USD")
            or Decimal(row["rate"]) <= 0
        ):
            raise ValueError("Unsupported or invalid input rate")
    rng = random.Random(seed)
    trades, payments, expected = [], [], []

    def payment(reference, currency, direction, day, amount):
        payments.append(
            {
                "payment_id": f"P{len(payments) + 1:09d}",
                "reference": reference,
                "currency": currency,
                "direction": direction,
                "payment_date": day.isoformat(),
                "amount": money(amount),
            }
        )

    for index in range(count):
        row = rng.choice(rates)
        day = date.fromisoformat(row["rate_date"])
        due = business_days(day, 2)
        base, quote = row["pair"].split("/")
        amount = Decimal(rng.randint(10_000, 1_000_000))
        quote_amount = Decimal(
            money(
                amount
                * Decimal(row["rate"]).quantize(
                    Decimal("0.00000000000001"), rounding=ROUND_HALF_UP
                )
            )
        )
        side = rng.choice(("BUY_BASE", "SELL_BASE"))
        base_direction = "receive" if side == "BUY_BASE" else "pay"
        quote_direction = "pay" if side == "BUY_BASE" else "receive"
        trade_id = f"T{index + 1:08d}"
        scenario = SCENARIOS[index % len(SCENARIOS)]
        trades.append(
            {
                "trade_id": trade_id,
                "pair": row["pair"],
                "counterparty": f"CP{rng.randint(1, 20):02d}",
                "side": side,
                "rate_date": day.isoformat(),
                "trade_date": day.isoformat(),
                "settlement_date": due.isoformat(),
                "base_amount": money(amount),
                "quote_amount": money(quote_amount),
                "rate_source_sha256": row["source_sha256"],
            }
        )
        reference = trade_id + ":B"
        allocated, late = amount, False
        if scenario == "split":
            first = Decimal(money(amount * Decimal("0.4")))
            payment(reference, base, base_direction, due, first)
            payment(reference, base, base_direction, due, amount - first)
        elif scenario == "partial":
            allocated = Decimal(money(amount / 2))
            payment(reference, base, base_direction, due, allocated)
        elif scenario == "missing":
            allocated = Decimal(0)
        elif scenario == "duplicate":
            payment(reference, base, base_direction, due, amount)
            payment(reference, base, base_direction, due, amount)
        elif scenario == "wrong_currency":
            allocated = Decimal(0)
            payment(reference, quote, base_direction, due, amount)
        elif scenario == "late":
            late = True
            payment(reference, base, base_direction, business_days(due, 1), amount)
        elif scenario == "overpaid":
            payment(reference, base, base_direction, due, amount * Decimal("1.2"))
        else:
            payment(reference, base, base_direction, due, amount)
        payment(trade_id + ":Q", quote, quote_direction, due, quote_amount)
        for leg, currency, total, applied, is_late, label in (
            ("B", base, amount, allocated, late, scenario),
            ("Q", quote, quote_amount, quote_amount, False, "exact"),
        ):
            expected.append(
                {
                    "leg_id": trade_id + ":" + leg,
                    "currency": currency,
                    "allocated": money(applied),
                    "outstanding": money(total - applied),
                    "is_late": is_late,
                    "scenario": label,
                }
            )
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "trades.csv", trades)
    write_csv(output / "payments.csv", payments)
    (output / "expected.json").write_text(
        json.dumps(expected, sort_keys=True, separators=(",", ":"))
    )
    manifest = {
        "classification": "synthetic",
        "generator_version": 1,
        "seed": seed,
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "trade_count": count,
        "payment_count": len(payments),
        "rate_source_sha256": rates[0]["source_sha256"],
        "rates_input_sha256": hashlib.sha256(rates_path.read_bytes()).hexdigest(),
        "as_of_date": (
            max(date.fromisoformat(t["settlement_date"]) for t in trades)
            + timedelta(days=5)
        ).isoformat(),
        "conventions": "Two gross legs; two weekdays to settle; no holiday calendars, spreads or netting",
        "files": {
            name: {
                "sha256": hashlib.sha256((output / name).read_bytes()).hexdigest(),
                "bytes": (output / name).stat().st_size,
            }
            for name in ("trades.csv", "payments.csv", "expected.json")
        },
    }
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (output / "manifest.json").write_bytes(encoded)
    batch_id = hashlib.sha256(encoded).hexdigest()
    return batch_id, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rates", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    batch, manifest = generate(args.rates, args.output, args.count, args.seed)
    print(
        json.dumps(
            {
                "batch_id": batch,
                "trades": manifest["trade_count"],
                "payments": manifest["payment_count"],
            }
        )
    )


if __name__ == "__main__":
    main()
