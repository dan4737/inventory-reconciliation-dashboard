# Inventory Reconciliation & KPI Dashboard

An interactive dashboard that reconciles a brewery's **Warehouse Management
System (WMS)** against **SAP** for month-end reporting and tracks the operational
KPIs an inventory analyst owns — every panel backed by real SQL.

**[🔗 Live Demo](URL)** · *(deployed on Streamlit Community Cloud — link added after deploy)*

---

## The problem

Inventory analysts in supply chain spend month-end reconciling two systems that
should agree but rarely do: the warehouse floor system (WMS) and the financial
system of record (SAP). Counts drift, records go missing on one side, and
in-transit deliveries age past their ETAs and need expediting. On top of that the
analyst owns service KPIs — fill rate, count accuracy, returnable-packaging loss.

This project mirrors that real operational work end-to-end: it generates a
realistic dataset with **intentional WMS-vs-SAP discrepancies**, detects and
classifies them in SQL, and presents the reconciliation and KPIs in a dashboard a
non-technical stakeholder can actually use.

## What it demonstrates

- **SQL** — `FULL OUTER JOIN` reconciliation (with the portable `LEFT JOIN … UNION`
  fallback documented), **window functions** (running variance by region), and
  reusable **VIEWs** as a single source of truth for KPIs.
- **Python** — a pandas/stdlib data pipeline that seeds a SQLite database with
  realistic synthetic data and deliberate, controlled discrepancies.
- **Dashboarding** — a Streamlit + Plotly UI with cross-cutting filters, where
  every chart traces back to a query in `sql/`.
- **Data modeling** — a small star-style schema (fact tables + a SKU dimension)
  and KPI definitions chosen to reflect genuine inventory-analyst metrics.

## Screenshots

> _Add after deploying._
>
> `![KPI cards & reconciliation](docs/screenshot-1.png)`
> `![In-transit aging & packaging loss](docs/screenshot-2.png)`

## How it works

```
data/seed_data.py  ──generates──▶  inventory.db  (SQLite, 5 tables + KPI views)
                                        │
        sql/*.sql  ──read at runtime──▶ │
                                        ▼
                                     app.py  (Streamlit dashboard)
```

- `data/seed_data.py` builds five tables (`wms_inventory`, `sap_inventory`,
  `in_transit`, `orders`, `returnable_packaging`) with ~44 brewery SKUs and
  controlled discrepancies, then creates the KPI views from `sql/03_kpi_views.sql`.
- `app.py` loads the queries from `sql/` (so the SQL stays the source of truth),
  caches results with `@st.cache_data`, and renders the panels.
- See [`sql/README.md`](sql/README.md) for a plain-English description of every query.

### Dashboard panels

| Panel | Backed by |
|---|---|
| Inventory Accuracy / Fill Rate / Transaction Accuracy cards | `vw_*` views in `03_kpi_views.sql` |
| WMS vs SAP reconciliation table (variance highlighted) | `01_reconciliation.sql` → `discrepancies` |
| Running variance by region | `01_reconciliation.sql` → `running_variance` (window fn) |
| In-transit aging + expedite queue | `02_intransit_aging.sql` → `aging` |
| Returnable packaging loss trend | `returnable_packaging` (inline query) |

Region and material-type filters in the sidebar drive every panel where the
dimension applies.

## Note on data

All data is **synthetic**, generated locally by `data/seed_data.py` with a fixed
random seed. No real company data is used. Discrepancies are introduced on purpose
so the reconciliation and KPIs have something meaningful to show (Inventory
Accuracy lands ~79%, Fill Rate ~97%, Transaction Accuracy ~89%).

## How to run locally

```bash
# 1. clone and enter
git clone <repo-url>
cd inventory-reconciliation-dashboard

# 2. create a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. install dependencies
pip install -r requirements.txt

# 4. generate the database
python data/seed_data.py

# 5. run the dashboard
streamlit run app.py
```

## Deploy to Streamlit Community Cloud

1. Push this repo to GitHub (make sure `inventory.db` is committed — see note below).
2. Go to **[share.streamlit.io](https://share.streamlit.io)** and sign in with GitHub.
3. Create a new app, pick this repo/branch, and set the main file to **`app.py`**.
4. Deploy — Streamlit installs `requirements.txt` and gives you a public URL to
   share with recruiters.

> **`inventory.db` is committed** so the deployed app has data immediately. To
> regenerate it instead of committing it, run `python data/seed_data.py` (e.g. as
> a startup step) — the schema and data are fully reproducible from the seed.

## Project structure

```
.
├── README.md
├── requirements.txt
├── app.py                     # Streamlit dashboard
├── inventory.db               # generated SQLite database (committed)
├── data/
│   └── seed_data.py           # generates inventory.db (synthetic data + discrepancies)
└── sql/
    ├── 01_reconciliation.sql  # WMS vs SAP FULL OUTER JOIN + running-variance window fn
    ├── 02_intransit_aging.sql # days-in-transit + aging buckets
    ├── 03_kpi_views.sql       # CREATE VIEW statements for the KPIs
    └── README.md              # plain-English explanation of every query
```
