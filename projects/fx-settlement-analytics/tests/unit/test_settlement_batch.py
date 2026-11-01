import json
import sys

import pytest

from pipeline.build_settlement_batch import main
from pipeline.generate_settlements import generate


def setup_batch(tmp_path, monkeypatch):
    rates = tmp_path / "rates.csv"
    rates.write_text(
        "rate_date,pair,rate,source_sha256\n2025-01-03,EUR/USD,1.25," + "a" * 64 + "\n"
    )
    source, output = tmp_path / "source", tmp_path / "output"
    batch, _ = generate(rates, source, count=8)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_settlement_batch",
            str(source),
            "--code-version",
            "test",
            "--output",
            str(output),
        ],
    )
    return source, output, batch


def test_verified_batch_links_inputs_and_run(tmp_path, monkeypatch):
    _, output, expected_batch = setup_batch(tmp_path, monkeypatch)
    main()
    batch = json.loads((output / "settlement-batch.json").read_text())
    sql = (output / "current-settlement-load.sql").read_text(encoding="utf-8-sig")
    assert batch["batch_id"] == expected_batch
    assert batch["trades"] == 8 and batch["payments"] == 17
    assert batch["run_id"] in sql and expected_batch in sql
    assert "warehouse.LoadSettlements" in sql


@pytest.mark.parametrize("name", ["trades.csv", "payments.csv", "expected.json"])
def test_tampered_inputs_never_create_a_load_command(tmp_path, monkeypatch, name):
    source, output, _ = setup_batch(tmp_path, monkeypatch)
    with (source / name).open("ab") as target:
        target.write(b"changed")
    with pytest.raises(ValueError, match="differs from manifest"):
        main()
    assert not (output / "current-settlement-load.sql").exists()
