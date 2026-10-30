# MyBestSim eSIM Catalogue Analytics

This project turns supplier eSIM CSV files into a validated, traceable analytical catalogue and an interactive Streamlit dashboard. It supports catalogue-level analysis of prices, data allowances, suppliers, destinations, and offer characteristics for the MyBestSim recruitment assessment.

## Overview

Supplier CSVs are discovered and loaded deterministically, validated, conservatively cleaned, and enriched with analytical fields. The pipeline then calculates metrics and aggregations used by the dashboard; source observations and provenance remain available throughout.

`Supplier CSVs -> ingestion -> validation -> cleaning and transformation -> metrics -> dashboard`

## Dashboard

The Streamlit interface is in French by design. It provides catalogue KPIs, supplier price comparisons, destination and regional coverage, price distribution and price-per-GB analysis, and breakdowns by network, plan type, and top-up availability. Users can explore offer rows and filter by supplier, destination, network, plan type, top-up, and price range. Data-quality findings and calculation methodology are also available in the app.

## Key Catalogue Metrics

Verified by running the current pipeline against `data/raw/`. Price metrics use eligible EUR offers; the median is shown rounded to two decimal places.

| Metric | Current baseline |
| --- | ---: |
| Supplier CSV files | 18 |
| Offers | 5,056 |
| Suppliers | 18 |
| Destinations / zones | 54 |
| Average price | €29.30 |
| Median price | €20.70 |
| Price range | €5.36 to €154.63 |
| Offers priced above €100 | 56 |
| Finite-data plans | 4,403 |
| Unlimited plans | 653 |
| Average finite allowance | 14.49 GB |
| 5G offers | 1,754 |
| Offers with top-up | 2,738 |

## Data Engineering Approach

- CSV discovery is recursive and sorted by relative path; every discovered file receives an explicit load report.
- CSV values are read as strings, avoiding implicit type coercion and null parsing. Required columns, record structure, and reserved provenance columns are checked during ingestion.
- Validation runs before cleaning and emits findings with rule, severity, and source location where available. A malformed file is rejected atomically without preventing other files from being attempted.
- Cleaning preserves every ingested row and its original numeric tokens, adding parsed analytical values, eligibility, and exclusion reasons rather than silently dropping records.
- Transformation derives flags and price-per-GB only where the underlying values are valid and eligible. Metrics and aggregations are separate from the dashboard, and dashboard filters reuse the same metric definitions.
- Each row carries its source file and logical record number; ingestion reports also include a SHA-256 digest for readable files.

## Important Data Decisions

- **Unlimited plans:** `data_gb` stays null for unlimited offers. They are not assigned zero, infinity, or an estimated allowance. Average allowance and price-per-GB use eligible finite-data plans only.
- **`NA` destination:** The CSV loader preserves literal values instead of applying pandas' default NA conversion. `NA` is the valid North America / Amérique du Nord destination code; 192 offers use it in the current data.
- **Duplicates:** Validation classifies repeated `(provider, sku)` identities, including identical and conflicting records. Cleaning retains all occurrences but marks every repeated identity analytically ineligible; it does not choose a winning row or resolve duplicates automatically. The current baseline contains no repeated identities.
- **Outliers:** Validation enforces business and representation rules, not statistical outlier cutoffs. High prices or large allowances are not removed solely for being extreme.
- **Currency:** EUR metrics are calculated without currency conversion. Non-EUR rows are ineligible for EUR price metrics.

## Data Quality & Validation

The current baseline discovers and loads all 18 files and ingests 5,056 rows. All 5,056 rows pass validation and are analytically eligible; there are no failed files, validation findings, or repeated supplier/SKU identities. The dashboard exposes per-file load status and row counts, overall quality totals, and row provenance remains in the analytical catalogue. These are results for the supplied snapshot, not a guarantee about future supplier files.

## Project Structure

```text
Yourfolder/
├── app.py
├── assets/
│   ├── bestsim.png
│   ├── dashboard.css
│   └── world_context.svg
├── data/
│   └── raw/                 # Supplier CSV files
├── src/
│   ├── cleaning.py
│   ├── config.py
│   ├── filtering.py
│   ├── loader.py
│   ├── metrics.py
│   ├── pipeline.py
│   ├── transformation.py
│   └── validation.py
├── tests/                   # Pipeline, dashboard, and visualization tests
├── requirements.txt
└── README.md
```

## Running Locally

Clone the repository, then from its root create and activate a virtual environment. Replace `<repository-url>` with the URL provided for this repository.

```bash
git clone <repository-url>
cd your chemin
python -m venv .venv
```

Activate the environment in PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Or on macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies, run the tests, and launch the dashboard:

```bash
python -m pip install -r requirements.txt
python -m pytest -q
streamlit run app.py
```

## Testing

The complete test suite currently passes: **97 passed**. Tests cover CSV discovery and ingestion, schema and business validation, cleaning and duplicate eligibility, transformations, metric denominators, filtering, dashboard behavior and regression cases, and price visualization.

## Technology Stack

- Python
- pandas
- Streamlit
- Plotly
- pytest

## AI-Assisted Development

AI tools were used as engineering assistants for repository analysis, implementation support, test generation and review, and documentation. Data assumptions and business rules were checked against the supplied CSVs; proposed code and final outputs were reviewed and tested rather than accepted blindly.

## Deployment

The repository contains no deployment configuration or live dashboard URL. Live dashboard: **[deployment pending]**.

## Possible Improvements

- Schedule supplier-file ingestion and retain timestamped catalogue snapshots.
- Add continuous integration to run tests on changes.
- Add operational monitoring and alerts for ingestion failures or data-quality regressions.
