-- ============================================================================
-- 03_kpi_views.sql  —  Reusable VIEWs (single source of truth for the KPIs)
-- ----------------------------------------------------------------------------
-- Executed by data/seed_data.py after the tables are loaded. Defining the KPIs
-- as views means the dashboard, ad-hoc SQL, and any future report all read the
-- exact same numbers.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- vw_sku_dim — small SKU dimension (sku -> description, material_type).
-- Lets fact tables that only store `sku` (orders, in_transit) be filtered by
-- material type without duplicating that attribute everywhere.
-- ----------------------------------------------------------------------------
DROP VIEW IF EXISTS vw_sku_dim;
CREATE VIEW vw_sku_dim AS
SELECT sku, MAX(description) AS description, MAX(material_type) AS material_type
FROM (
    SELECT sku, description, material_type FROM wms_inventory
    UNION
    SELECT sku, description, material_type FROM sap_inventory
)
GROUP BY sku;


-- ----------------------------------------------------------------------------
-- vw_reconciliation — one row per sku+batch comparing WMS vs SAP.
-- This is the base view the reconciliation KPIs are built on. See
-- 01_reconciliation.sql for notes on the FULL OUTER JOIN (and the portable
-- LEFT JOIN ... UNION fallback for SQLite < 3.39).
-- ----------------------------------------------------------------------------
DROP VIEW IF EXISTS vw_reconciliation;
CREATE VIEW vw_reconciliation AS
SELECT
    COALESCE(w.sku, s.sku)                    AS sku,
    COALESCE(w.description, s.description)     AS description,
    COALESCE(w.material_type, s.material_type) AS material_type,
    COALESCE(w.region, s.region)              AS region,
    COALESCE(w.batch, s.batch)                AS batch,
    w.quantity                                AS wms_qty,
    s.quantity                                AS sap_qty,
    COALESCE(w.quantity, 0) - COALESCE(s.quantity, 0) AS variance,
    CASE
        WHEN w.sku IS NULL             THEN 'Missing in WMS'
        WHEN s.sku IS NULL             THEN 'Missing in SAP'
        WHEN w.quantity <> s.quantity  THEN 'Quantity Mismatch'
        ELSE 'Match'
    END AS discrepancy_type
FROM wms_inventory w
FULL OUTER JOIN sap_inventory s
    ON w.sku = s.sku AND w.batch = s.batch;


-- ----------------------------------------------------------------------------
-- KPI 1 — vw_inventory_accuracy
-- Business meaning: of every inventory record we should be able to reconcile,
-- what share matches EXACTLY between WMS and SAP (present in both, same qty)?
-- This is the headline month-end count-accuracy number, by region + overall.
-- ----------------------------------------------------------------------------
DROP VIEW IF EXISTS vw_inventory_accuracy;
CREATE VIEW vw_inventory_accuracy AS
SELECT
    region,
    SUM(CASE WHEN discrepancy_type = 'Match' THEN 1 ELSE 0 END) AS matched_records,
    COUNT(*)                                                    AS total_records,
    ROUND(100.0 * SUM(CASE WHEN discrepancy_type = 'Match' THEN 1 ELSE 0 END)
          / COUNT(*), 1)                                        AS accuracy_pct
FROM vw_reconciliation
GROUP BY region
UNION ALL
SELECT
    'Overall',
    SUM(CASE WHEN discrepancy_type = 'Match' THEN 1 ELSE 0 END),
    COUNT(*),
    ROUND(100.0 * SUM(CASE WHEN discrepancy_type = 'Match' THEN 1 ELSE 0 END)
          / COUNT(*), 1)
FROM vw_reconciliation;


-- ----------------------------------------------------------------------------
-- KPI 2 — vw_order_fill_rate
-- Business meaning: of everything customers ordered, what share did we actually
-- ship? Units shipped / units ordered, by region + overall. The customer-facing
-- service-level KPI.
-- ----------------------------------------------------------------------------
DROP VIEW IF EXISTS vw_order_fill_rate;
CREATE VIEW vw_order_fill_rate AS
SELECT
    region,
    SUM(quantity_shipped) AS units_shipped,
    SUM(quantity_ordered) AS units_ordered,
    ROUND(100.0 * SUM(quantity_shipped) / SUM(quantity_ordered), 1) AS fill_rate_pct
FROM orders
GROUP BY region
UNION ALL
SELECT
    'Overall',
    SUM(quantity_shipped),
    SUM(quantity_ordered),
    ROUND(100.0 * SUM(quantity_shipped) / SUM(quantity_ordered), 1)
FROM orders;


-- ----------------------------------------------------------------------------
-- KPI 3 — vw_transaction_accuracy
-- Business meaning: of the records that exist in BOTH systems (i.e. a posting
-- happened on both sides), what share carry zero variance? Treats each
-- co-present sku/batch as a transaction. This isolates *value* accuracy from the
-- *existence* accuracy measured by KPI 1, so the two numbers differ meaningfully.
-- ----------------------------------------------------------------------------
DROP VIEW IF EXISTS vw_transaction_accuracy;
CREATE VIEW vw_transaction_accuracy AS
SELECT
    region,
    SUM(CASE WHEN discrepancy_type = 'Match' THEN 1 ELSE 0 END) AS zero_variance_txns,
    SUM(CASE WHEN discrepancy_type IN ('Match', 'Quantity Mismatch')
             THEN 1 ELSE 0 END)                                 AS total_txns,
    ROUND(100.0 * SUM(CASE WHEN discrepancy_type = 'Match' THEN 1 ELSE 0 END)
          / NULLIF(SUM(CASE WHEN discrepancy_type IN ('Match', 'Quantity Mismatch')
                            THEN 1 ELSE 0 END), 0), 1)          AS accuracy_pct
FROM vw_reconciliation
GROUP BY region
UNION ALL
SELECT
    'Overall',
    SUM(CASE WHEN discrepancy_type = 'Match' THEN 1 ELSE 0 END),
    SUM(CASE WHEN discrepancy_type IN ('Match', 'Quantity Mismatch') THEN 1 ELSE 0 END),
    ROUND(100.0 * SUM(CASE WHEN discrepancy_type = 'Match' THEN 1 ELSE 0 END)
          / NULLIF(SUM(CASE WHEN discrepancy_type IN ('Match', 'Quantity Mismatch')
                            THEN 1 ELSE 0 END), 0), 1)
FROM vw_reconciliation;
