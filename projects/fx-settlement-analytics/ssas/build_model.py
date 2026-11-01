"""Generate the SSAS model from explicit SQL view contracts and DAX measures."""

import json
from pathlib import Path

TABLES = {
    "Batch": [
        ("BatchId", "string"),
        ("SimulationAsOf", "dateTime"),
        ("ReconciledAsOf", "dateTime"),
        ("Seed", "int64"),
        ("TradeCount", "int64"),
        ("IsSynthetic", "boolean"),
    ],
    "Currency": [("Currency", "string")],
    "Direction": [("Direction", "string")],
    "Counterparty": [("Counterparty", "string"), ("DisplayName", "string")],
    "CurrencyPair": [("Pair", "string")],
    "SettlementDate": [
        ("Date", "dateTime"),
        ("Year", "int64"),
        ("Month", "int64"),
        ("Day", "int64"),
    ],
    "SettlementLeg": [
        ("BatchId", "string"),
        ("LegId", "string"),
        ("TradeId", "string"),
        ("Counterparty", "string"),
        ("Pair", "string"),
        ("Currency", "string"),
        ("Direction", "string"),
        ("DueDate", "dateTime"),
        ("ExpectedAmount", "decimal"),
        ("AllocatedAmount", "decimal"),
        ("OutstandingAmount", "decimal"),
        ("IsLate", "int64"),
        ("IsOverdue", "int64"),
        ("SettlementStatus", "string"),
    ],
    "Payment": [
        ("BatchId", "string"),
        ("PaymentId", "string"),
        ("Reference", "string"),
        ("Currency", "string"),
        ("Direction", "string"),
        ("PaymentDate", "dateTime"),
        ("Amount", "decimal"),
        ("AllocatedAmount", "decimal"),
        ("UnappliedAmount", "decimal"),
        ("PaymentStatus", "string"),
        ("Counterparty", "string"),
        ("Pair", "string"),
    ],
}
BATCH = "HASONEVALUE('Batch'[BatchId])"
MONEY = BATCH + " && HASONEVALUE('Currency'[Currency])"


def guarded(expression, monetary=False):
    return f"IF({MONEY if monetary else BATCH}, {expression}, BLANK())"


def build():
    tables, relationships = [], []
    for name, columns in TABLES.items():
        table = {
            "name": name,
            "columns": [
                {
                    "name": col,
                    "dataType": kind,
                    "sourceColumn": col,
                    **({"formatString": "#,0.00"} if kind == "decimal" else {}),
                }
                for col, kind in columns
            ],
            "partitions": [
                {
                    "name": name,
                    "mode": "import",
                    "source": {
                        "type": "query",
                        "dataSource": "FxWarehouse",
                        "query": "SELECT "
                        + ",".join(f"[{col}]" for col, _ in columns)
                        + f" FROM analytics.[{name}]",
                    },
                }
            ],
        }
        tables.append(table)
    measures = {
        "Expected Legs": guarded("COALESCE(COUNTROWS('SettlementLeg'),0)"),
        "Settled Legs": guarded(
            "COALESCE(CALCULATE(COUNTROWS('SettlementLeg'),'SettlementLeg'[SettlementStatus]=\"settled\"),0)"
        ),
        "Outstanding Legs": guarded(
            "COALESCE(CALCULATE(COUNTROWS('SettlementLeg'),'SettlementLeg'[OutstandingAmount]>0),0)"
        ),
        "Overdue Legs": guarded(
            "COALESCE(CALCULATE(COUNTROWS('SettlementLeg'),'SettlementLeg'[IsOverdue]=1),0)"
        ),
        "Late Legs": guarded(
            "COALESCE(CALCULATE(COUNTROWS('SettlementLeg'),'SettlementLeg'[IsLate]=1),0)"
        ),
        "Trades": guarded("COALESCE(DISTINCTCOUNT('SettlementLeg'[TradeId]),0)"),
        "Leg Settlement Rate": "DIVIDE([Settled Legs],[Expected Legs])",
        "Gross Expected": guarded(
            "COALESCE(SUM('SettlementLeg'[ExpectedAmount]),0)", True
        ),
        "Gross Allocated": guarded(
            "COALESCE(SUM('SettlementLeg'[AllocatedAmount]),0)", True
        ),
        "Gross Outstanding": guarded(
            "COALESCE(SUM('SettlementLeg'[OutstandingAmount]),0)", True
        ),
        "Payments": guarded("COALESCE(COUNTROWS('Payment'),0)"),
        "Payment Exceptions": guarded(
            "COALESCE(CALCULATE(COUNTROWS('Payment'),'Payment'[PaymentStatus]<>\"matched\"),0)"
        ),
        "Duplicate Candidates": guarded(
            "COALESCE(CALCULATE(COUNTROWS('Payment'),'Payment'[PaymentStatus]=\"duplicate_candidate\"),0)"
        ),
        "Overpaid Payments": guarded(
            "COALESCE(CALCULATE(COUNTROWS('Payment'),'Payment'[PaymentStatus]=\"overpayment\"),0)"
        ),
        "Unapplied Payment Amount": guarded(
            "COALESCE(SUM('Payment'[UnappliedAmount]),0)", True
        ),
    }
    tables[-2]["measures"] = [
        {
            "name": name,
            "expression": expression,
            "formatString": "0.00%"
            if name.endswith("Rate")
            else "#,0.00"
            if name
            in (
                "Gross Expected",
                "Gross Allocated",
                "Gross Outstanding",
                "Unapplied Payment Amount",
            )
            else "#,0",
        }
        for name, expression in measures.items()
    ]
    dimensions = [
        ("Batch", "BatchId"),
        ("Currency", "Currency"),
        ("Counterparty", "Counterparty"),
        ("CurrencyPair", "Pair"),
        ("Direction", "Direction"),
    ]
    for fact in ("SettlementLeg", "Payment"):
        for dimension, column in dimensions:
            relationships.append(
                {
                    "name": f"{fact}_{dimension}",
                    "fromTable": fact,
                    "fromColumn": column,
                    "toTable": dimension,
                    "toColumn": column,
                    "crossFilteringBehavior": "oneDirection",
                }
            )
    relationships.append(
        {
            "name": "SettlementLeg_DueDate",
            "fromTable": "SettlementLeg",
            "fromColumn": "DueDate",
            "toTable": "SettlementDate",
            "toColumn": "Date",
            "crossFilteringBehavior": "oneDirection",
        }
    )
    return {
        "name": "FxSettlement",
        "compatibilityLevel": 1500,
        "model": {
            "culture": "en-GB",
            "dataSources": [
                {
                    "name": "FxWarehouse",
                    "type": "provider",
                    "connectionString": "Provider=MSOLEDBSQL;Data Source=localhost;Initial Catalog=FxWarehouse;Integrated Security=SSPI;Trust Server Certificate=True;",
                    "impersonationMode": "impersonateServiceAccount",
                }
            ],
            "tables": tables,
            "relationships": relationships,
            "roles": [
                {
                    "name": "DashboardReaders",
                    "modelPermission": "read",
                    "members": [
                        {
                            "memberName": "NT AUTHORITY\\LOCAL SERVICE",
                            "memberId": "S-1-5-19",
                        }
                    ],
                }
            ],
        },
    }


if __name__ == "__main__":
    destination = Path(__file__).with_name("Model.bim")
    destination.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"Generated {destination}")
