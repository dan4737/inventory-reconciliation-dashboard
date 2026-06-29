"""
Inventory Reconciliation & KPI Dashboard
========================================
A Streamlit dashboard for a brewery inventory analyst. Every panel is backed by
a real SQL query against `inventory.db`:

  * KPI cards            -> sql/03_kpi_views.sql  (vw_inventory_accuracy, ...)
  * Reconciliation table -> sql/01_reconciliation.sql  (FULL OUTER JOIN)
  * Running variance     -> sql/01_reconciliation.sql  (window function)
  * In-transit aging     -> sql/02_intransit_aging.sql
  * Returnable packaging -> queried inline from returnable_packaging

Run:  streamlit run app.py
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# ---------------------------------------------------------------------------
# Paths & SQL loading
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "inventory.db"
SQL_DIR = ROOT / "sql"

st.set_page_config(
    page_title="Inventory Reconciliation & KPI Dashboard",
    page_icon="🍺",
    layout="wide",
)


@st.cache_data(show_spinner=False)
def load_named_query(filename: str, name: str) -> str:
    """Return a single named query block from a .sql file.

    Blocks are delimited by lines of the form `-- name: <name>`. Keeping the SQL
    in the .sql files (not inline strings) makes those files the single source of
    truth — exactly what a reviewer would want to read.
    """
    text = (SQL_DIR / filename).read_text()
    parts = re.split(r"^--\s*name:\s*(\w+)\s*$", text, flags=re.M)
    blocks = {parts[i].strip(): parts[i + 1] for i in range(1, len(parts), 2)}
    if name not in blocks:
        raise KeyError(f"Query '{name}' not found in {filename}")
    return blocks[name]


def get_connection() -> sqlite3.Connection:
    if not DB_PATH.exists():
        st.error(
            "`inventory.db` not found. Generate it first:\n\n"
            "```\npython data/seed_data.py\n```"
        )
        st.stop()
    return sqlite3.connect(DB_PATH, check_same_thread=False)


@st.cache_data(show_spinner=False)
def run_query(sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Filter-aware data accessors
# ---------------------------------------------------------------------------
def kpis(region: str, material_type: str) -> dict[str, float | None]:
    """Return the three KPI percentages for the current filter selection.

    When no material-type filter is active the cards read straight from the
    pre-built SQL views (the canonical numbers). When a material-type filter is
    applied we recompute using the SAME view logic with a WHERE clause, so the
    drill-down stays consistent with the headline figures.
    """
    scope = "Overall" if region == "All" else region

    def one(sql: str, params: tuple = ()) -> float | None:
        df = run_query(sql, params)
        if df.empty or df.iat[0, 0] is None:
            return None
        return float(df.iat[0, 0])

    if material_type == "All":
        inv = one(
            "SELECT accuracy_pct FROM vw_inventory_accuracy WHERE region = ?", (scope,)
        )
        txn = one(
            "SELECT accuracy_pct FROM vw_transaction_accuracy WHERE region = ?", (scope,)
        )
        fill = one(
            "SELECT fill_rate_pct FROM vw_order_fill_rate WHERE region = ?", (scope,)
        )
        return {"inventory": inv, "transaction": txn, "fill": fill}

    # Material-type filter active -> recompute on the same view logic.
    where = "WHERE material_type = ?"
    p: tuple = (material_type,)
    if region != "All":
        where += " AND region = ?"
        p = (material_type, region)

    inv = one(
        f"""SELECT ROUND(100.0 * SUM(CASE WHEN discrepancy_type='Match' THEN 1 ELSE 0 END)
                   / COUNT(*), 1)
            FROM vw_reconciliation {where}""",
        p,
    )
    txn = one(
        f"""SELECT ROUND(100.0 * SUM(CASE WHEN discrepancy_type='Match' THEN 1 ELSE 0 END)
                   / NULLIF(SUM(CASE WHEN discrepancy_type IN ('Match','Quantity Mismatch')
                                     THEN 1 ELSE 0 END), 0), 1)
            FROM vw_reconciliation {where}""",
        p,
    )
    # Fill rate: orders carry only sku, so join the SKU dimension for material_type.
    fwhere = "WHERE d.material_type = ?"
    fp: tuple = (material_type,)
    if region != "All":
        fwhere += " AND o.region = ?"
        fp = (material_type, region)
    fill = one(
        f"""SELECT ROUND(100.0 * SUM(o.quantity_shipped) / SUM(o.quantity_ordered), 1)
            FROM orders o LEFT JOIN vw_sku_dim d ON o.sku = d.sku {fwhere}""",
        fp,
    )
    return {"inventory": inv, "transaction": txn, "fill": fill}


def apply_filters(df: pd.DataFrame, region: str, material_type: str) -> pd.DataFrame:
    out = df
    if region != "All" and "region" in out.columns:
        out = out[out["region"] == region]
    if material_type != "All" and "material_type" in out.columns:
        out = out[out["material_type"] == material_type]
    return out


# ---------------------------------------------------------------------------
# Sidebar (filters)
# ---------------------------------------------------------------------------
st.sidebar.header("Filters")
region = st.sidebar.selectbox("Region", ["All", "East", "West"])
material_type = st.sidebar.selectbox(
    "Material type", ["All", "Raw Material", "Finished Good"]
)
st.sidebar.caption(
    "Filters drive every panel below where the dimension applies "
    "(packaging-loss is region-only)."
)
st.sidebar.divider()
st.sidebar.markdown(
    "**Data is synthetic.** Generated by `data/seed_data.py` — no real company "
    "data is used."
)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("🍺 Inventory Reconciliation & KPI Dashboard")
st.markdown(
    "Month-end reconciliation of a brewery's **Warehouse Management System (WMS)** "
    "against **SAP**, plus the operational KPIs an inventory analyst owns. "
    "Every panel is powered by a real SQL query against a SQLite database — "
    "all data is **synthetic**."
)

# ---------------------------------------------------------------------------
# Phase 1 — KPI cards
# ---------------------------------------------------------------------------
st.subheader("Key Performance Indicators")
k = kpis(region, material_type)


def fmt(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1f}%"


c1, c2, c3 = st.columns(3)
c1.metric("Inventory Accuracy", fmt(k["inventory"]))
c1.caption("WMS records that match SAP exactly (present in both, same qty).")
c2.metric("Order Fill Rate", fmt(k["fill"]))
c2.caption("Units shipped ÷ units ordered.")
c3.metric("Transaction Accuracy", fmt(k["transaction"]))
c3.caption("Of records in both systems, the share with zero variance.")

st.divider()

# ---------------------------------------------------------------------------
# Phase 1 — Reconciliation table (WMS vs SAP)
# ---------------------------------------------------------------------------
st.subheader("WMS vs SAP Reconciliation")
st.caption(
    "FULL OUTER JOIN of WMS against SAP on sku + batch. Each row is classified as "
    "a Quantity Mismatch, Missing in SAP, or Missing in WMS — these are the "
    "exceptions an analyst chases down at month-end."
)

recon_all = run_query(load_named_query("01_reconciliation.sql", "discrepancies"))
recon = apply_filters(recon_all, region, material_type)

show_matched = st.checkbox("Show matched rows too", value=False)
recon_view = recon if show_matched else recon[recon["discrepancy_type"] != "Match"]

# Summary chips of how many of each discrepancy type are in view.
counts = recon[recon["discrepancy_type"] != "Match"]["discrepancy_type"].value_counts()
m1, m2, m3 = st.columns(3)
m1.metric("Quantity Mismatch", int(counts.get("Quantity Mismatch", 0)))
m2.metric("Missing in SAP", int(counts.get("Missing in SAP", 0)))
m3.metric("Missing in WMS", int(counts.get("Missing in WMS", 0)))


def highlight_variance(val):
    try:
        return "color: #d62728; font-weight: 600;" if val and float(val) != 0 else ""
    except (TypeError, ValueError):
        return ""


display_cols = [
    "sku", "description", "region", "batch",
    "wms_qty", "sap_qty", "variance", "discrepancy_type",
]
if recon_view.empty:
    st.info("No rows for the current filter selection.")
else:
    styled = (
        recon_view[display_cols]
        .reset_index(drop=True)
        .style.map(highlight_variance, subset=["variance"])
        .format({"wms_qty": "{:.0f}", "sap_qty": "{:.0f}", "variance": "{:+.0f}"},
                na_rep="—")
    )
    st.dataframe(styled, use_container_width=True, height=380)

# Window-function showcase: running variance by region.
with st.expander("📈 Running variance by region (SQL window function)"):
    st.caption(
        "SUM(variance) OVER (PARTITION BY region ORDER BY sku, batch) — cumulative "
        "net drift between WMS and SAP within each region."
    )
    rv_all = run_query(load_named_query("01_reconciliation.sql", "running_variance"))
    rv = rv_all if region == "All" else rv_all[rv_all["region"] == region]
    if rv.empty:
        st.info("No data for the current selection.")
    else:
        rv = rv.reset_index(drop=True)
        rv["step"] = rv.groupby("region").cumcount()
        fig_rv = px.line(
            rv, x="step", y="running_variance", color="region",
            labels={"step": "SKU/batch sequence", "running_variance": "Running variance (units)"},
        )
        fig_rv.add_hline(y=0, line_dash="dot", line_color="gray")
        st.plotly_chart(fig_rv, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Phase 2 — In-transit aging
# ---------------------------------------------------------------------------
st.subheader("In-Transit Aging & Expedite Queue")
st.caption(
    "Shipments bucketed by aging. Overdue = past expected arrival and still in "
    "transit — the analyst's expedite priorities, surfaced at the top."
)

aging_all = run_query(load_named_query("02_intransit_aging.sql", "aging"))
aging = apply_filters(aging_all, region, material_type)

if aging.empty:
    st.info("No shipments for the current filter selection.")
else:
    bucket_order = ["Overdue", "At Risk", "On Time", "Delivered"]
    counts = (
        aging["aging_bucket"].value_counts()
        .reindex(bucket_order).fillna(0).astype(int).reset_index()
    )
    counts.columns = ["aging_bucket", "shipments"]

    left, right = st.columns([1, 1])
    with left:
        color_map = {
            "Overdue": "#d62728", "At Risk": "#ff7f0e",
            "On Time": "#2ca02c", "Delivered": "#7f7f7f",
        }
        fig_age = px.bar(
            counts, x="aging_bucket", y="shipments", color="aging_bucket",
            category_orders={"aging_bucket": bucket_order},
            color_discrete_map=color_map,
            labels={"aging_bucket": "Aging bucket", "shipments": "Shipments"},
        )
        fig_age.update_layout(showlegend=False)
        st.plotly_chart(fig_age, use_container_width=True)
    with right:
        overdue = aging[aging["aging_bucket"] == "Overdue"]
        st.markdown("**Expedite queue (most overdue first)**")
        if overdue.empty:
            st.success("Nothing overdue for this selection. 🎉")
        else:
            st.dataframe(
                overdue[
                    ["shipment_id", "sku", "origin", "region",
                     "expected_arrival", "days_past_due", "quantity"]
                ].reset_index(drop=True),
                use_container_width=True, height=320,
            )

st.divider()

# ---------------------------------------------------------------------------
# Phase 2 — Returnable packaging loss
# ---------------------------------------------------------------------------
st.subheader("Returnable Packaging Loss")
st.caption(
    "Monthly keg/pallet loss by region (issued − returned). A KPI the analyst "
    "owns — sustained loss erodes the returnable-asset pool."
)

pkg = run_query(
    """SELECT region, period, issued, returned, (issued - returned) AS loss
       FROM returnable_packaging ORDER BY period"""
)
if region != "All":
    pkg = pkg[pkg["region"] == region]

if pkg.empty:
    st.info("No packaging data for the current selection.")
else:
    pkg = pkg.copy()
    pkg["period"] = pd.to_datetime(pkg["period"])
    fig_pkg = px.line(
        pkg, x="period", y="loss", color="region", markers=True,
        labels={"period": "Month", "loss": "Units lost", "region": "Region"},
    )
    st.plotly_chart(fig_pkg, use_container_width=True)

    total_loss = int(pkg["loss"].sum())
    total_issued = int(pkg["issued"].sum())
    loss_rate = (100.0 * total_loss / total_issued) if total_issued else 0
    a, b, c = st.columns(3)
    a.metric("Total units issued", f"{total_issued:,}")
    b.metric("Total units lost", f"{total_loss:,}")
    c.metric("Loss rate", f"{loss_rate:.1f}%")

st.divider()
st.caption(
    "Built with SQLite · pandas · Streamlit · Plotly. "
    "SQL lives in `sql/`; data is generated by `data/seed_data.py`. "
    "All data is synthetic."
)
