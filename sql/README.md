# SQL — query reference

Plain-English explanation of each query. The dashboard loads individual queries
by their `-- name:` marker, so each file can hold several runnable blocks while
remaining the single source of truth for the SQL.

## `01_reconciliation.sql`

**`discrepancies`** — Compares WMS against SAP for every `sku + batch` using a
`FULL OUTER JOIN`, so records that exist in only one system still appear. Each row
is classified as:

| `discrepancy_type` | meaning |
|---|---|
| `Match` | present in both systems, identical quantity |
| `Quantity Mismatch` | present in both, quantities differ |
| `Missing in SAP` | exists in WMS but not SAP |
| `Missing in WMS` | exists in SAP but not WMS |

`variance = wms_qty − sap_qty`. Results are ordered so exceptions surface first.

> **SQLite note:** `FULL OUTER JOIN` is supported natively from SQLite 3.39
> (this repo runs 3.45). On older engines, emulate it with
> `LEFT JOIN ... UNION ... LEFT JOIN (… WHERE wms.sku IS NULL)` — there's a
> worked example in the file's header comment.

**`running_variance`** — A **window function** (`SUM(variance) OVER (PARTITION BY
region ORDER BY sku, batch)`) producing a cumulative net-variance balance within
each region. Shows whether a region is trending net-over or net-under SAP.

## `02_intransit_aging.sql`

**`aging`** — Ages every in-transit shipment and assigns an aging bucket:

| bucket | rule |
|---|---|
| `Overdue` | past `expected_arrival` **and** still `In Transit` (expedite now) |
| `At Risk` | within 2 days of `expected_arrival` |
| `On Time` | more than 2 days before `expected_arrival` |
| `Delivered` | already received |

`days_in_transit` runs from `ship_date` to today (or to `expected_arrival` for
delivered shipments). Ordered most-overdue-first so the top of the list is the
expedite work queue. Joins `vw_sku_dim` for description / material type.

## `03_kpi_views.sql`

Reusable **VIEWs** (executed by `data/seed_data.py` after the tables load):

- **`vw_sku_dim`** — SKU → description, material type. Lets fact tables that only
  store `sku` (`orders`, `in_transit`) be filtered by material type.
- **`vw_reconciliation`** — the base WMS-vs-SAP comparison the reconciliation
  KPIs are built on (same logic as `01`'s `discrepancies`).
- **`vw_inventory_accuracy`** — *Inventory Accuracy*: share of records that match
  exactly (present in both, same qty), by region + overall.
- **`vw_order_fill_rate`** — *Order Fill Rate*: `SUM(quantity_shipped) /
  SUM(quantity_ordered)`, by region + overall.
- **`vw_transaction_accuracy`** — *Transaction Accuracy*: of records present in
  both systems, the share with zero variance — isolates value accuracy from the
  existence accuracy measured by Inventory Accuracy.
