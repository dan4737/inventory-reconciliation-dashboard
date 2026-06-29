"""
seed_data.py
============
Generates `inventory.db` (SQLite) for the Inventory Reconciliation & KPI Dashboard.

It creates five tables with realistic-but-synthetic brewery data and *intentionally*
seeds discrepancies between the Warehouse Management System (WMS) and SAP so that the
reconciliation query and KPI views surface something meaningful:

    wms_inventory         - what the warehouse system says
    sap_inventory         - what SAP says (system of record)
    in_transit            - deliveries on the move (some aged past ETA)
    orders                - customer orders, for the fill-rate KPI
    returnable_packaging  - kegs/pallets issued vs returned, by region/month

After loading the tables, it executes `sql/03_kpi_views.sql` to (re)create the
reusable VIEWs that the dashboard reads from.

Run:  python data/seed_data.py
Only the Python standard library is required to generate the data.
"""

from __future__ import annotations

import datetime as dt
import random
import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Deterministic seed so the database (and therefore the KPIs) are reproducible.
RNG = random.Random(42)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "inventory.db"
KPI_VIEWS_SQL = PROJECT_ROOT / "sql" / "03_kpi_views.sql"

REGIONS = ["East", "West"]
WAREHOUSES = {
    "East": ["DC-East-01", "Brewery-East"],
    "West": ["DC-West-01", "Brewery-West"],
}

TODAY = dt.date.today()
# Month-end physical count snapshot = last day of the previous month.
SNAPSHOT_DATE = (TODAY.replace(day=1) - dt.timedelta(days=1)).isoformat()


# ---------------------------------------------------------------------------
# SKU catalogue (raw materials + finished goods)
# ---------------------------------------------------------------------------
def build_catalogue() -> list[dict]:
    """Return ~50 brewery SKUs with description + material_type."""
    raw_materials = [
        ("Pale Two-Row Malt 50lb", "RM-MALT"),
        ("Pilsner Malt 50lb", "RM-MALT"),
        ("Munich Malt 50lb", "RM-MALT"),
        ("Crystal 60L Malt 50lb", "RM-MALT"),
        ("Chocolate Malt 50lb", "RM-MALT"),
        ("Wheat Malt 50lb", "RM-MALT"),
        ("Roasted Barley 50lb", "RM-MALT"),
        ("Vienna Malt 50lb", "RM-MALT"),
        ("Cascade Hops Pellets 11lb", "RM-HOP"),
        ("Citra Hops Pellets 11lb", "RM-HOP"),
        ("Mosaic Hops Pellets 11lb", "RM-HOP"),
        ("Centennial Hops Pellets 11lb", "RM-HOP"),
        ("Saaz Hops Pellets 11lb", "RM-HOP"),
        ("Hallertau Hops Pellets 11lb", "RM-HOP"),
        ("Simcoe Hops Pellets 11lb", "RM-HOP"),
        ("Amarillo Hops Pellets 11lb", "RM-HOP"),
        ("Ale Yeast US-05 Brick", "RM-YST"),
        ("Lager Yeast W-34/70 Brick", "RM-YST"),
        ("Belgian Ale Yeast Brick", "RM-YST"),
        ("Hefeweizen Yeast Brick", "RM-YST"),
        ("12oz Amber Bottle (pallet)", "RM-PKG"),
        ("16oz Can Blank (sleeve)", "RM-PKG"),
        ("Bottle Crown Caps (case)", "RM-PKG"),
        ("6-pack Carrier (bundle)", "RM-PKG"),
        ("Corrugated Case (bundle)", "RM-PKG"),
        ("1/2 BBL Keg Shell", "RM-PKG"),
        ("1/6 BBL Keg Shell", "RM-PKG"),
        ("Pressure Sensitive Labels (roll)", "RM-PKG"),
    ]
    finished_goods = [
        ("Hop Forward IPA 6pk 12oz Bottle", "FG-IPA"),
        ("Hop Forward IPA 4pk 16oz Can", "FG-IPA"),
        ("Hop Forward IPA 1/2 BBL Keg", "FG-IPA"),
        ("Hazy Pale Ale 6pk 12oz Can", "FG-PALE"),
        ("Hazy Pale Ale 1/6 BBL Keg", "FG-PALE"),
        ("Czech Pilsner 12pk 12oz Bottle", "FG-PILS"),
        ("Czech Pilsner 1/2 BBL Keg", "FG-PILS"),
        ("Amber Lager 6pk 12oz Bottle", "FG-LAGER"),
        ("Light Lager 12pk 12oz Can", "FG-LAGER"),
        ("Dry Stout 4pk 16oz Can", "FG-STOUT"),
        ("Dry Stout 1/6 BBL Keg", "FG-STOUT"),
        ("Hefeweizen 6pk 12oz Bottle", "FG-WHEAT"),
        ("Saison Seasonal 4pk 16oz Can", "FG-SAISON"),
        ("Robust Porter 6pk 12oz Bottle", "FG-PORTER"),
        ("Double IPA 4pk 16oz Can", "FG-DIPA"),
        ("Double IPA 1/6 BBL Keg", "FG-DIPA"),
    ]

    catalogue: list[dict] = []
    counters: dict[str, int] = {}
    for desc, prefix in raw_materials + finished_goods:
        counters[prefix] = counters.get(prefix, 0) + 1
        sku = f"{prefix}-{counters[prefix]:03d}"
        material_type = "Raw Material" if prefix.startswith("RM") else "Finished Good"
        catalogue.append(
            {"sku": sku, "description": desc, "material_type": material_type}
        )
    return catalogue


# ---------------------------------------------------------------------------
# Inventory base rows -> WMS / SAP with intentional discrepancies
# ---------------------------------------------------------------------------
def build_inventory(catalogue: list[dict]) -> tuple[list[tuple], list[tuple]]:
    """Build base inventory line rows, then derive WMS & SAP with discrepancies.

    Each base row has a globally-unique batch, so (sku, batch) is a clean key for
    the FULL OUTER JOIN in the reconciliation query.
    """
    base: list[dict] = []
    batch_counter = 1000
    for item in catalogue:
        for _ in range(RNG.randint(2, 5)):  # a few batches/locations per SKU
            region = RNG.choice(REGIONS)
            warehouse = RNG.choice(WAREHOUSES[region])
            batch_counter += 1
            if item["material_type"] == "Raw Material":
                qty = RNG.randint(40, 1800)
            else:
                qty = RNG.randint(20, 900)
            base.append(
                {
                    "sku": item["sku"],
                    "description": item["description"],
                    "material_type": item["material_type"],
                    "region": region,
                    "warehouse": warehouse,
                    "batch": f"B{batch_counter}",
                    "quantity": qty,
                }
            )

    n = len(base)
    idx = list(range(n))
    RNG.shuffle(idx)

    # Discrepancy budget (~15% of rows are "off" -> ~85% clean matches).
    k_missing_sap = round(n * 0.06)   # present in WMS, absent in SAP
    k_missing_wms = round(n * 0.05)   # present in SAP, absent in WMS
    k_mismatch = round(n * 0.10)      # present in both, different quantity

    missing_in_sap = set(idx[:k_missing_sap])
    missing_in_wms = set(idx[k_missing_sap:k_missing_sap + k_missing_wms])
    quantity_mismatch = set(
        idx[k_missing_sap + k_missing_wms:k_missing_sap + k_missing_wms + k_mismatch]
    )

    def row_tuple(r: dict, qty: int) -> tuple:
        return (
            r["sku"], r["description"], r["material_type"], r["region"],
            r["warehouse"], r["batch"], qty, SNAPSHOT_DATE,
        )

    wms_rows: list[tuple] = []
    sap_rows: list[tuple] = []
    for i, r in enumerate(base):
        if i in missing_in_sap:
            wms_rows.append(row_tuple(r, r["quantity"]))          # WMS only
        elif i in missing_in_wms:
            sap_rows.append(row_tuple(r, r["quantity"]))          # SAP only
        elif i in quantity_mismatch:
            wms_rows.append(row_tuple(r, r["quantity"]))
            # SAP off by a small +/- delta (count error during put-away/posting).
            spread = max(1, int(r["quantity"] * 0.20))
            delta = RNG.choice([-1, 1]) * RNG.randint(1, spread)
            sap_rows.append(row_tuple(r, max(0, r["quantity"] + delta)))
        else:
            wms_rows.append(row_tuple(r, r["quantity"]))          # clean match
            sap_rows.append(row_tuple(r, r["quantity"]))

    return wms_rows, sap_rows


# ---------------------------------------------------------------------------
# In-transit shipments (some aged past ETA = expedite candidates)
# ---------------------------------------------------------------------------
def build_in_transit(catalogue: list[dict]) -> list[tuple]:
    suppliers = [
        "Great Lakes Malting", "Pacific Hop Growers", "Yeast Labs Intl",
        "ContainerCo Packaging", "Midwest Grain Co", "Yakima Hop Supply",
    ]
    rows: list[tuple] = []
    for i in range(36):
        item = RNG.choice(catalogue)
        ship_offset = RNG.randint(1, 42)            # shipped 1-42 days ago
        ship_date = TODAY - dt.timedelta(days=ship_offset)
        lead_time = RNG.randint(5, 21)
        expected = ship_date + dt.timedelta(days=lead_time)

        if expected < TODAY:
            # Past ETA: roughly half were delivered, half are stuck (overdue).
            status = "In Transit" if RNG.random() < 0.5 else "Delivered"
        else:
            status = "In Transit"

        rows.append(
            (
                f"SHP-{2600 + i:04d}",
                item["sku"],
                RNG.randint(10, 600),
                RNG.choice(suppliers),
                RNG.choice(REGIONS),
                ship_date.isoformat(),
                expected.isoformat(),
                status,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Orders (finished goods) for the fill-rate KPI
# ---------------------------------------------------------------------------
def build_orders(catalogue: list[dict]) -> list[tuple]:
    finished = [c for c in catalogue if c["material_type"] == "Finished Good"]
    rows: list[tuple] = []
    for i in range(95):
        item = RNG.choice(finished)
        region = RNG.choice(REGIONS)
        ordered = RNG.randint(10, 500)
        # ~22% of orders ship short (stockouts / partial allocation).
        if RNG.random() < 0.22:
            short = RNG.randint(1, max(1, int(ordered * 0.30)))
            shipped = ordered - short
        else:
            shipped = ordered
        order_date = TODAY - dt.timedelta(days=RNG.randint(0, 60))
        rows.append(
            (
                f"SO-{50000 + i}",
                item["sku"],
                region,
                ordered,
                shipped,
                order_date.isoformat(),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Returnable packaging (kegs/pallets) loss by region/month
# ---------------------------------------------------------------------------
def build_returnable_packaging() -> list[tuple]:
    rows: list[tuple] = []
    # 12 monthly periods, ending last month, for each region.
    first_of_this_month = TODAY.replace(day=1)
    for region in REGIONS:
        for m in range(12, 0, -1):
            # walk back m months from the first of this month
            year = first_of_this_month.year
            month = first_of_this_month.month - m
            while month <= 0:
                month += 12
                year -= 1
            period = dt.date(year, month, 1).isoformat()
            issued = RNG.randint(800, 1500)
            returned = issued - RNG.randint(20, 200)  # loss = issued - returned
            rows.append((region, period, issued, returned))
    return rows


# ---------------------------------------------------------------------------
# Database build
# ---------------------------------------------------------------------------
SCHEMA = """
DROP TABLE IF EXISTS wms_inventory;
DROP TABLE IF EXISTS sap_inventory;
DROP TABLE IF EXISTS in_transit;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS returnable_packaging;

CREATE TABLE wms_inventory (
    sku           TEXT,
    description   TEXT,
    material_type TEXT,
    region        TEXT,
    warehouse     TEXT,
    batch         TEXT,
    quantity      INTEGER,
    snapshot_date DATE
);

CREATE TABLE sap_inventory (
    sku           TEXT,
    description   TEXT,
    material_type TEXT,
    region        TEXT,
    warehouse     TEXT,
    batch         TEXT,
    quantity      INTEGER,
    snapshot_date DATE
);

CREATE TABLE in_transit (
    shipment_id        TEXT,
    sku                TEXT,
    quantity           INTEGER,
    origin             TEXT,
    destination_region TEXT,
    ship_date          DATE,
    expected_arrival   DATE,
    status             TEXT
);

CREATE TABLE orders (
    order_id         TEXT,
    sku              TEXT,
    region           TEXT,
    quantity_ordered INTEGER,
    quantity_shipped INTEGER,
    order_date       DATE
);

CREATE TABLE returnable_packaging (
    region   TEXT,
    period   DATE,
    issued   INTEGER,
    returned INTEGER
);
"""


def main() -> None:
    catalogue = build_catalogue()
    wms_rows, sap_rows = build_inventory(catalogue)
    in_transit_rows = build_in_transit(catalogue)
    orders_rows = build_orders(catalogue)
    packaging_rows = build_returnable_packaging()

    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO wms_inventory VALUES (?,?,?,?,?,?,?,?)", wms_rows
        )
        conn.executemany(
            "INSERT INTO sap_inventory VALUES (?,?,?,?,?,?,?,?)", sap_rows
        )
        conn.executemany(
            "INSERT INTO in_transit VALUES (?,?,?,?,?,?,?,?)", in_transit_rows
        )
        conn.executemany(
            "INSERT INTO orders VALUES (?,?,?,?,?,?)", orders_rows
        )
        conn.executemany(
            "INSERT INTO returnable_packaging VALUES (?,?,?,?)", packaging_rows
        )
        conn.commit()

        # (Re)create the reusable KPI views from the SQL file = single source of truth.
        if KPI_VIEWS_SQL.exists():
            conn.executescript(KPI_VIEWS_SQL.read_text())
            conn.commit()
        else:
            print(f"WARNING: {KPI_VIEWS_SQL} not found - views not created.")

        _print_summary(conn, catalogue, wms_rows, sap_rows,
                       in_transit_rows, orders_rows, packaging_rows)
    finally:
        conn.close()


def _print_summary(conn, catalogue, wms_rows, sap_rows,
                   in_transit_rows, orders_rows, packaging_rows) -> None:
    print(f"Database written to: {DB_PATH}")
    print(f"  SKUs in catalogue          : {len(catalogue)}")
    print(f"  wms_inventory rows         : {len(wms_rows)}")
    print(f"  sap_inventory rows         : {len(sap_rows)}")
    print(f"  in_transit rows            : {len(in_transit_rows)}")
    print(f"  orders rows                : {len(orders_rows)}")
    print(f"  returnable_packaging rows  : {len(packaging_rows)}")

    cur = conn.cursor()
    try:
        rows = cur.execute(
            "SELECT discrepancy_type, COUNT(*) FROM vw_reconciliation "
            "GROUP BY discrepancy_type ORDER BY 1"
        ).fetchall()
        print("  reconciliation breakdown   :")
        for dtype, cnt in rows:
            print(f"      {dtype:<20} {cnt}")

        for view, label in [
            ("vw_inventory_accuracy", "Inventory Accuracy"),
            ("vw_order_fill_rate", "Order Fill Rate"),
            ("vw_transaction_accuracy", "Transaction Accuracy"),
        ]:
            pct = cur.execute(
                f"SELECT accuracy_pct FROM {view} WHERE region='Overall'"
                if view != "vw_order_fill_rate"
                else "SELECT fill_rate_pct FROM vw_order_fill_rate WHERE region='Overall'"
            ).fetchone()
            print(f"  {label:<26} : {pct[0]}%")
    except sqlite3.OperationalError as exc:
        print(f"  (KPI summary skipped: {exc})")


if __name__ == "__main__":
    main()
