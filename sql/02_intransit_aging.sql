-- ============================================================================
-- 02_intransit_aging.sql  —  In-transit aging & expedite prioritisation
-- ============================================================================


-- name: aging
-- ----------------------------------------------------------------------------
-- Age every in-transit shipment and bucket it so the analyst knows what to
-- expedite. Thresholds (commented inline) are deliberately conservative:
--
--   * days_in_transit : ship_date -> today           (for shipments still moving)
--                       ship_date -> expected_arrival (for delivered shipments)
--   * AT-RISK window   : within 2 days of the expected arrival date
--   * OVERDUE          : past expected_arrival AND still 'In Transit'
--
-- vw_sku_dim (created in 03_kpi_views.sql) supplies description + material_type
-- so the dashboard's material-type filter works on this panel too.
SELECT
    t.shipment_id,
    t.sku,
    d.description,
    d.material_type,
    t.quantity,
    t.origin,
    t.destination_region                AS region,
    t.ship_date,
    t.expected_arrival,
    t.status,
    CAST(
        julianday(CASE WHEN t.status = 'Delivered'
                       THEN t.expected_arrival
                       ELSE DATE('now') END)
        - julianday(t.ship_date)
    AS INTEGER)                          AS days_in_transit,
    -- positive => already past the expected arrival date
    CAST(julianday(DATE('now')) - julianday(t.expected_arrival) AS INTEGER)
                                         AS days_past_due,
    CASE
        WHEN t.status = 'Delivered' THEN 'Delivered'
        WHEN julianday(DATE('now')) > julianday(t.expected_arrival)
            THEN 'Overdue'                                        -- expedite now
        WHEN julianday(DATE('now')) >= julianday(t.expected_arrival) - 2
            THEN 'At Risk'                                        -- within 2 days
        ELSE 'On Time'
    END AS aging_bucket
FROM in_transit t
LEFT JOIN vw_sku_dim d ON t.sku = d.sku
-- Most overdue first => the top of the list is the expedite work queue.
ORDER BY
    CASE WHEN t.status = 'In Transit'
              AND julianday(DATE('now')) > julianday(t.expected_arrival)
         THEN 0 ELSE 1 END,
    days_past_due DESC,
    days_in_transit DESC;
