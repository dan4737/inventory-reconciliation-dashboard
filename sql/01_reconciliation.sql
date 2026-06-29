-- ============================================================================
-- 01_reconciliation.sql  —  WMS vs SAP discrepancy detection
-- ----------------------------------------------------------------------------
-- The dashboard loads individual queries from this file by their "-- name:"
-- marker, so each block below is independently runnable.
-- ============================================================================


-- name: discrepancies
-- ----------------------------------------------------------------------------
-- Compare what the Warehouse Management System (WMS) holds against SAP (the
-- system of record) for every sku + batch, and classify the difference.
--
-- FULL OUTER JOIN is used so rows that exist in only ONE system still appear.
-- SQLite supports FULL OUTER JOIN natively since v3.39 (this repo's runtime is
-- 3.45). On an OLDER SQLite you must emulate it, because the engine would error:
--
--     SELECT ... FROM wms_inventory w LEFT JOIN sap_inventory s
--         ON w.sku = s.sku AND w.batch = s.batch
--     UNION
--     SELECT ... FROM sap_inventory s LEFT JOIN wms_inventory w
--         ON w.sku = s.sku AND w.batch = s.batch
--     WHERE w.sku IS NULL;          -- only the SAP-only rows the first half missed
--
-- The native FULL OUTER JOIN below is clearer, so we use it.
SELECT
    COALESCE(w.sku, s.sku)                   AS sku,
    COALESCE(w.description, s.description)    AS description,
    COALESCE(w.material_type, s.material_type) AS material_type,
    COALESCE(w.region, s.region)             AS region,
    COALESCE(w.batch, s.batch)               AS batch,
    w.quantity                               AS wms_qty,
    s.quantity                               AS sap_qty,
    COALESCE(w.quantity, 0) - COALESCE(s.quantity, 0) AS variance,
    CASE
        WHEN w.sku IS NULL              THEN 'Missing in WMS'   -- only SAP has it
        WHEN s.sku IS NULL             THEN 'Missing in SAP'    -- only WMS has it
        WHEN w.quantity <> s.quantity  THEN 'Quantity Mismatch' -- both, qty differs
        ELSE 'Match'
    END AS discrepancy_type
FROM wms_inventory w
FULL OUTER JOIN sap_inventory s
    ON w.sku = s.sku AND w.batch = s.batch
ORDER BY
    CASE
        WHEN w.sku IS NULL OR s.sku IS NULL THEN 0   -- surface missing rows first
        WHEN w.quantity <> s.quantity       THEN 1
        ELSE 2
    END,
    ABS(COALESCE(w.quantity, 0) - COALESCE(s.quantity, 0)) DESC;


-- name: running_variance
-- ----------------------------------------------------------------------------
-- Window-function view of the data: a running balance of net variance within
-- each region, accumulated SKU by SKU. This is the kind of cumulative drift an
-- analyst watches to see whether a region is trending net-over or net-under SAP.
WITH recon AS (
    SELECT
        COALESCE(w.region, s.region) AS region,
        COALESCE(w.sku, s.sku)       AS sku,
        COALESCE(w.batch, s.batch)   AS batch,
        COALESCE(w.quantity, 0) - COALESCE(s.quantity, 0) AS variance
    FROM wms_inventory w
    FULL OUTER JOIN sap_inventory s
        ON w.sku = s.sku AND w.batch = s.batch
)
SELECT
    region,
    sku,
    batch,
    variance,
    SUM(variance) OVER (
        PARTITION BY region
        ORDER BY sku, batch
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS running_variance
FROM recon
ORDER BY region, sku, batch;
