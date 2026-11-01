import csv
import json
from decimal import Decimal

import pytest

from pipeline.generate_settlements import generate


def input_rates(tmp_path):
    path = tmp_path / "rates.csv"
    path.write_text(
        "rate_date,pair,rate,source_sha256\n2025-01-03,EUR/USD,1.25," + "a" * 64 + "\n"
    )
    return path


def test_reproducible_inputs_and_manifest(tmp_path):
    rates = input_rates(tmp_path)
    a, b = tmp_path / "a", tmp_path / "b"
    first, _ = generate(rates, a, count=8, seed=42)
    second, _ = generate(rates, b, count=8, seed=42)
    assert first == second
    for name in ("trades.csv", "payments.csv", "expected.json", "manifest.json"):
        assert (a / name).read_bytes() == (b / name).read_bytes()
    other, _ = generate(rates, tmp_path / "c", count=8, seed=43)
    assert other != first


def test_known_trade_amounts_dates_and_all_scenarios(tmp_path):
    output = tmp_path / "out"
    _, manifest = generate(input_rates(tmp_path), output, count=8)
    with (output / "trades.csv").open() as source:
        trades = list(csv.DictReader(source))
    with (output / "payments.csv").open() as source:
        payments = list(csv.DictReader(source))
    expected = json.loads((output / "expected.json").read_text())
    assert len(trades) == 8 and len(payments) == 17 and len(expected) == 16
    assert manifest["classification"] == "synthetic"
    for trade in trades:
        assert trade["settlement_date"] == "2025-01-07"  # Friday plus two weekdays.
        assert Decimal(trade["quote_amount"]) == Decimal(
            trade["base_amount"]
        ) * Decimal("1.25")
    base = {row["scenario"]: row for row in expected if row["leg_id"].endswith(":B")}
    assert Decimal(base["missing"]["allocated"]) == 0
    assert Decimal(base["partial"]["allocated"]) == Decimal(
        base["partial"]["outstanding"]
    )
    assert base["late"]["is_late"] is True
    assert Decimal(base["wrong_currency"]["allocated"]) == 0
    assert len({p["payment_id"] for p in payments}) == 17
    duplicate = [p for p in payments if p["reference"] == "T00000005:B"]
    assert len(duplicate) == 2 and duplicate[0]["amount"] == duplicate[1]["amount"]


@pytest.mark.parametrize("count", [0, 7, 100001])
def test_generation_is_bounded(tmp_path, count):
    with pytest.raises(ValueError, match="Trade count"):
        generate(input_rates(tmp_path), tmp_path / "out", count=count)
