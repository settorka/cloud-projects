"""Run on Windows as the dashboard reader, against real SQL and SSAS."""

import json
from decimal import Decimal
from pathlib import Path

import dashboard_data as data
from pipeline.connections import sql

identity = sql(
    "SELECT ORIGINAL_LOGIN() AS LoginName,IS_SRVROLEMEMBER('sysadmin') AS IsAdmin,HAS_PERMS_BY_NAME('analytics','SCHEMA','SELECT') AS CanRead,HAS_PERMS_BY_NAME('warehouse.FactTrade','OBJECT','INSERT') AS CanWrite;"
)[0]
assert identity["LoginName"].upper() == "NT AUTHORITY\\LOCAL SERVICE"
assert (
    identity["IsAdmin"] == 0 and identity["CanRead"] == 1 and identity["CanWrite"] != 1
)
batch = data.batches()[0]
selected = data.filters(batch["BatchId"], "GBP")
metrics = data.metrics(selected)
assert metrics["ExpectedLegs"] > 0
assert isinstance(metrics["GrossOutstanding"], Decimal)
assert data.lineage(batch["BatchId"], "T00000001")
assert data.health()

from streamlit.testing.v1 import AppTest

app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
app.run(timeout=90)
assert not app.exception and not app.error, "Dashboard initial render failed"
assert len(app.metric) >= 4
app.sidebar.selectbox[1].set_value("USD").run(timeout=90)
assert not app.exception and not app.error, "Currency filter render failed"
app.sidebar.selectbox[2].set_value("EUR/USD").run(timeout=90)
assert not app.exception and not app.error, "Pair filter render failed"
print(
    json.dumps(
        {
            "status": "passed",
            "identity": identity,
            "ui_metrics": len(app.metric),
            "batch": batch["BatchId"],
        }
    )
)
