from pathlib import Path

root = Path(__file__).resolve().parents[1]
expected = (root / "contracts/event.schema.json").read_bytes()
for service in ["trading", "market-data", "valuation"]:
    assert (root / f"services/{service}/app/event.schema.json").read_bytes() == expected, service
print("All service event schemas match the versioned contract")
