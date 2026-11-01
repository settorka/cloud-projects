"""Read-only FX settlement analytics, served by Streamlit on the Windows VM."""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import dashboard_data as data

logger = logging.getLogger(__name__)

st.set_page_config(page_title="FX Settlement Analytics", page_icon="↔", layout="wide")
cache = st.cache_data(ttl=30, show_spinner=False)
read_batches = data.batches
read_metrics = cache(data.metrics)
read_payment_metrics = cache(data.payment_metrics)
read_settlements = cache(data.settlement_details)
read_payments = cache(data.payment_details)
read_summary = cache(data.due_summary)
read_bounds = cache(data.due_bounds)
read_health = cache(data.health)
read_lineage = cache(data.lineage)


def main():
    st.title("FX settlement analytics")
    st.caption("ECB reference rates · SQL Server warehouse · SSAS measures")
    st.info(
        "Historical simulation: trades, payments and counterparties are synthetic. This dashboard does not show live bank activity."
    )
    state_path = Path(__file__).with_name(".state") / "model.json"
    state = (
        json.loads(state_path.read_text(encoding="utf-8-sig"))
        if state_path.exists()
        else {}
    )
    if state.get("status") != "verified":
        st.warning(
            "The analytics model is being refreshed or has not passed validation. Metrics will be available after a successful refresh."
        )
        return
    if st.session_state.get("model_verified_at") != state["verified_at"]:
        st.cache_data.clear()
        st.session_state["model_verified_at"] = state["verified_at"]
    st.caption(f"Analytics model verified: {state['verified_at']}")
    available = read_batches()
    if not available:
        st.warning("No reconciled settlement batch is available yet.")
        return
    lookup = {row["BatchId"]: row for row in available}
    with st.sidebar:
        st.header("Settlement scope")
        batch_id = st.selectbox(
            "Simulation batch",
            list(lookup),
            format_func=lambda key: (
                f"{lookup[key]['TradeCount']:,} trades · seed {lookup[key]['Seed']} · {key[:8]}"
            ),
        )
        currency = st.selectbox("Currency", ["GBP", "EUR", "USD"])
        pair = st.selectbox(
            "Currency pair", ["All pairs", "GBP/USD", "EUR/GBP", "EUR/USD"]
        )
        counterparty = st.selectbox(
            "Counterparty",
            ["All counterparties"] + [f"CP{i:02d}" for i in range(1, 21)],
        )
        direction = st.selectbox(
            "Cash direction", ["Pay and receive", "pay", "receive"]
        )
        bounds = read_bounds(batch_id)
        dates = st.date_input(
            "Settlement due dates",
            value=(bounds["FirstDueDate"].date(), bounds["LastDueDate"].date()),
        )
        if len(dates) != 2:
            st.caption("Choose both ends of the date range.")
            st.stop()
        if st.button("Refresh data", width="stretch"):
            st.cache_data.clear()
            st.rerun()
        st.caption("Read-only. Query results are cached for up to 30 seconds.")
    batch = lookup[batch_id]
    selected = data.filters(
        batch_id,
        currency,
        None if pair == "All pairs" else pair,
        None if counterparty == "All counterparties" else counterparty,
        None if direction == "Pay and receive" else direction,
        tuple(dates),
    )
    st.caption(
        f"Simulation as-of: {batch['ReconciledAsOf']:%d %b %Y} · Warehouse reconciliation: {batch['ReconciledAt']:%d %b %Y %H:%M} UTC · {currency} amounts only"
    )
    if batch["ReconciledAt"] > datetime.fromisoformat(state["verified_at"]):
        st.warning(
            "This warehouse batch changed after the last verified analytics refresh. Refresh the model before viewing metrics."
        )
        return
    metrics = read_metrics(selected)
    columns = st.columns(4)
    columns[0].metric("Expected settlement legs", f"{metrics['ExpectedLegs']:,}")
    rate = metrics["SettlementRate"]
    columns[1].metric("Leg settlement rate", "—" if rate is None else f"{rate:.1%}")
    columns[2].metric(
        f"Gross outstanding · {currency}",
        f"{metrics['GrossOutstanding']:,.2f}",
        help="Positive outstanding pay and receive movements. This is not a net exposure measure.",
    )
    columns[3].metric("Overdue legs", f"{metrics['OverdueLegs']:,}")
    settlement_tab, payments_tab, lineage_tab, health_tab, constraints_tab = st.tabs(
        ["Settlements", "Payments", "Lineage", "Pipeline health", "Data constraints"]
    )
    with settlement_tab:
        st.subheader("Settlement exceptions")
        st.caption(
            f"{metrics['OutstandingLegs']:,} outstanding legs · {metrics['LateLegs']:,} legs with late allocated cash. Showing up to 200 exceptions."
        )
        details = read_settlements(selected)
        st.dataframe(pd.DataFrame(details), width="stretch", hide_index=True)
        summary = pd.DataFrame(read_summary(selected))
        if not summary.empty:
            summary["GrossOutstanding"] = summary["GrossOutstanding"].map(float)
            st.subheader(f"Gross outstanding by due date · {currency}")
            st.bar_chart(summary, x="DueDate", y="GrossOutstanding")
    with payments_tab:
        st.caption(
            "Payment measures cover all payments observed by the simulation as-of date. The due-date range above applies only to settlement legs."
        )
        payments = read_payment_metrics(selected)
        columns = st.columns(4)
        columns[0].metric("Payments", f"{payments['Payments']:,}")
        columns[1].metric("Payment exceptions", f"{payments['Exceptions']:,}")
        columns[2].metric("Duplicate candidates", f"{payments['Duplicates']:,}")
        columns[3].metric(f"Unapplied · {currency}", f"{payments['Unapplied']:,.2f}")
        st.caption(
            "Duplicate candidates require investigation; equal reference and amount do not prove duplication. Showing up to 200 exceptions."
        )
        st.dataframe(
            pd.DataFrame(read_payments(selected)), width="stretch", hide_index=True
        )
    with lineage_tab:
        st.subheader("Trace a trade to its source")
        trade = st.text_input("Trade identifier", value="T00000001", max_chars=9)
        if re.fullmatch(r"T[0-9]{8}", trade):
            st.dataframe(
                pd.DataFrame(read_lineage(batch_id, trade)),
                width="stretch",
                hide_index=True,
            )
        st.caption(
            "Trade and payment files are synthetic; rate source rows refer to the original ECB archive. Derived GBP/USD identifies both same-date input currencies."
        )
    with health_tab:
        runs = read_health()
        failed = sum(row["Status"] == "failed" for row in runs)
        if failed:
            st.warning(
                f"{failed} failed runs in the latest {len(runs)} executions. Inspect their error and rejection details."
            )
        else:
            st.success("No failures in the latest recorded executions.")
        st.dataframe(pd.DataFrame(runs), width="stretch", hide_index=True)
        st.caption(
            "Settlement exceptions are business outcomes. Rejected malformed inputs and failed executions are tracked separately."
        )
    with constraints_tab:
        st.markdown("""
- ECB provides daily informational reference rates, not executed trades, spreads or bank payments.
- GBP/USD is derived from same-date USD-per-EUR and GBP-per-EUR observations. Missing observations are not filled.
- Synthetic scenarios exercise exact, split, partial, missing, duplicate, wrong-currency, late and overpaid base legs. Quote legs are controls.
- Settlement dates use two weekdays, without currency holiday calendars. There is no netting or payment-versus-payment simulation.
- Amounts stay separated by currency and pay/receive direction. Monetary measures require one currency and one batch.
- The simulation as-of date is historical. It is separate from the time the warehouse was processed.
""")
        st.link_button(
            "ECB reference-rate source and limitations",
            "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html",
        )


try:
    main()
except Exception:
    logger.exception("Dashboard query failed")
    st.error(
        "The warehouse or analytics model is unavailable. Try refreshing, then inspect the server logs if the issue persists."
    )
