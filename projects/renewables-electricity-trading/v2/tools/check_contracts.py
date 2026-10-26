from pathlib import Path

root = Path(__file__).resolve().parents[1]
expected = (root / "contracts/event.schema.json").read_bytes()
for service in ["trading", "market-data", "valuation"]:
    assert (root / f"services/{service}/app/event.schema.json").read_bytes() == expected, service
print("All service event schemas match the versioned contract")

# Independently built images carry the same operational protocol implementation.
for relative in [
    "app/telemetry.py",
    "app/configuration.py",
    "app/processes.py",
    "app/events.py",
    "app/observability.py",
    "app/management/commands/process_history.py",
    "app/management/commands/operational_snapshot.py",
]:
    reference = (root / "services" / "trading" / relative).read_bytes()
    for service in ["market-data", "valuation"]:
        assert (root / "services" / service / relative).read_bytes() == reference, (
            f"Runtime helper drift: {service}/{relative}"
        )
print("All service tracing/state helpers match")
