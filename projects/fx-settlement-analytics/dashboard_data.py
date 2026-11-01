"""Read-only dashboard queries with shared filters and explicit monetary units."""

import re
from datetime import date

from pipeline.connections import dax, sql


def filters(batch, currency, pair=None, counterparty=None, direction=None, dates=None):
    if not re.fullmatch(r"[a-fA-F0-9]{64}", batch):
        raise ValueError("Invalid batch identifier")
    if currency not in ("GBP", "EUR", "USD"):
        raise ValueError("Select one supported currency")
    for value, allowed in (
        (pair, ("EUR/USD", "EUR/GBP", "GBP/USD")),
        (direction, ("pay", "receive")),
    ):
        if value is not None and value not in allowed:
            raise ValueError("Unsupported filter")
    if counterparty is not None and not re.fullmatch(
        r"CP(0[1-9]|1[0-9]|20)", counterparty
    ):
        raise ValueError("Unsupported counterparty")
    if dates is not None and (
        len(dates) != 2
        or not all(isinstance(d, date) for d in dates)
        or dates[0] > dates[1]
    ):
        raise ValueError("Select a valid due-date interval")
    return {
        "batch": batch,
        "currency": currency,
        "pair": pair,
        "counterparty": counterparty,
        "direction": direction,
        "dates": dates,
    }


def _dax_filters(selected, include_dates=True):
    selected = filters(**selected)
    columns = {
        "batch": "'Batch'[BatchId]",
        "currency": "'Currency'[Currency]",
        "pair": "'CurrencyPair'[Pair]",
        "counterparty": "'Counterparty'[Counterparty]",
        "direction": "'Direction'[Direction]",
    }
    parts = [
        f'TREATAS({{"{value}"}},{columns[key]})'
        for key, value in selected.items()
        if key in columns and value is not None
    ]
    if include_dates and selected.get("dates"):
        first, last = selected["dates"]
        parts.append(
            f"DATESBETWEEN('SettlementDate'[Date],DATE({first.year},{first.month},{first.day}),DATE({last.year},{last.month},{last.day}))"
        )
    return ",".join(parts)


def _sql_filters(selected, include_dates=True):
    selected = filters(**selected)
    columns = {
        "batch": "BatchId",
        "currency": "Currency",
        "pair": "Pair",
        "counterparty": "Counterparty",
        "direction": "Direction",
    }
    parameters = {
        key: value
        for key, value in selected.items()
        if key in columns and value is not None
    }
    clause = " AND ".join(f"[{columns[key]}]=@{key}" for key in parameters)
    if include_dates and selected.get("dates"):
        parameters.update(
            first=selected["dates"][0].isoformat(),
            last=selected["dates"][1].isoformat(),
        )
        clause += (
            " AND DueDate BETWEEN CONVERT(date,@first,23) AND CONVERT(date,@last,23)"
        )
    return clause, parameters


def batches():
    return sql(
        "SELECT BatchId,TradeCount,Seed,SimulationAsOf,ReconciledAsOf,ReconciledAt,IsSynthetic,RateSourceHash FROM analytics.Batch ORDER BY TradeCount DESC,BatchId;"
    )


def metrics(selected):
    measures = {
        "ExpectedLegs": "Expected Legs",
        "SettledLegs": "Settled Legs",
        "OutstandingLegs": "Outstanding Legs",
        "OverdueLegs": "Overdue Legs",
        "LateLegs": "Late Legs",
        "SettlementRate": "Leg Settlement Rate",
        "GrossExpected": "Gross Expected",
        "GrossAllocated": "Gross Allocated",
        "GrossOutstanding": "Gross Outstanding",
    }
    row = ",".join(f'"{label}",[{measure}]' for label, measure in measures.items())
    return dax(f"EVALUATE CALCULATETABLE(ROW({row}),{_dax_filters(selected)})")[0]


def payment_metrics(selected):
    row = '"Payments",[Payments],"Exceptions",[Payment Exceptions],"Duplicates",[Duplicate Candidates],"Overpaid",[Overpaid Payments],"Unapplied",[Unapplied Payment Amount]'
    return dax(f"EVALUATE CALCULATETABLE(ROW({row}),{_dax_filters(selected, False)})")[
        0
    ]


def settlement_details(selected):
    clause, parameters = _sql_filters(selected)
    return sql(
        "SELECT TOP (200) TradeId,LegId,Pair,Counterparty,Currency,Direction,DueDate,ExpectedAmount,AllocatedAmount,OutstandingAmount,IsLate,IsOverdue,SettlementStatus FROM analytics.SettlementLeg WHERE "
        + clause
        + " AND (OutstandingAmount>0 OR IsLate=1) ORDER BY OutstandingAmount DESC,LegId;",
        parameters,
    )


def payment_details(selected):
    clause, parameters = _sql_filters(selected, False)
    return sql(
        "SELECT TOP (200) PaymentId,Reference,Pair,Counterparty,Currency,Direction,PaymentDate,Amount,AllocatedAmount,UnappliedAmount,PaymentStatus FROM analytics.Payment WHERE "
        + clause
        + " AND PaymentStatus<>'matched' ORDER BY UnappliedAmount DESC,PaymentId;",
        parameters,
    )


def due_summary(selected):
    clause, parameters = _sql_filters(selected)
    return sql(
        "SELECT DueDate,COUNT(*) AS ExpectedLegs,SUM(CASE WHEN SettlementStatus='settled' THEN 1 ELSE 0 END) AS SettledLegs,SUM(OutstandingAmount) AS GrossOutstanding FROM analytics.SettlementLeg WHERE "
        + clause
        + " GROUP BY DueDate ORDER BY DueDate;",
        parameters,
    )


def due_bounds(batch):
    return sql(
        "SELECT MIN(DueDate) AS FirstDueDate,MAX(DueDate) AS LastDueDate FROM analytics.SettlementLeg WHERE BatchId=@batch;",
        {"batch": batch},
    )[0]


def lineage(batch, trade):
    if not re.fullmatch(r"T[0-9]{8}", trade):
        raise ValueError("Invalid trade identifier")
    return sql(
        "SELECT * FROM analytics.TradeLineage WHERE BatchId=@batch AND TradeId=@trade;",
        {"batch": batch, "trade": trade},
    )


def health():
    return sql(
        "SELECT TOP (30) RunId,Pipeline,Status,StartedAt,FinishedAt,ElapsedMs,RowsReceived,RowsLoaded,RowsInserted,RowsRejected,RecordedRejections,SsisExecutionId,CodeVersion,ErrorMessage FROM analytics.PipelineHealth ORDER BY StartedAt DESC;"
    )
