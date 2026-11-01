import csv
import hashlib
import io
import json
import sys
import zipfile

import pytest

from pipeline.build_rate_batch import main


def inputs(tmp_path, monkeypatch):
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("eurofxref-hist.csv", "Date,USD,GBP\n2025-01-02,1.25,0.80\n")
    payload = content.getvalue()
    source = tmp_path / "source.zip"
    source.write_bytes(payload)
    manifest = {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "source_url": "https://example.test/ECB's-rates",
        "retrieved_at": "2025-01-03T00:00:00Z",
    }
    metadata = tmp_path / "manifest.json"
    metadata.write_text(json.dumps(manifest))
    output = tmp_path / "output"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_rate_batch",
            str(source),
            str(metadata),
            "--start",
            "2025-01-01",
            "--end",
            "2025-01-31",
            "--code-version",
            "test",
            "--output",
            str(output),
        ],
    )
    return metadata, manifest, output


def test_known_rates_and_source_provenance(tmp_path, monkeypatch):
    _, manifest, output = inputs(tmp_path, monkeypatch)
    main()
    with (output / "fx_rates.csv").open() as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 3
    cross = next(row for row in rows if row["pair"] == "GBP/USD")
    assert cross["rate"] == "1.5625"
    assert cross["source_sha256"] == manifest["sha256"]
    batch = json.loads((output / "batch.json").read_text())
    sql = (output / "current-rate-load.sql").read_text(encoding="utf-8-sig")
    assert batch["run_id"] in sql
    assert batch["rows"] == 3
    assert "https://example.test/ECB''s-rates" in sql


def test_mismatched_manifest_cannot_produce_loadable_batch(tmp_path, monkeypatch):
    metadata, manifest, output = inputs(tmp_path, monkeypatch)
    manifest["sha256"] = "0" * 64
    metadata.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="hash differ"):
        main()
    assert not (output / "current-rate-load.sql").exists()


def test_incorrect_manifest_size_cannot_produce_loadable_batch(tmp_path, monkeypatch):
    metadata, manifest, output = inputs(tmp_path, monkeypatch)
    manifest["bytes"] += 1
    metadata.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="byte count differ"):
        main()
    assert not (output / "current-rate-load.sql").exists()
