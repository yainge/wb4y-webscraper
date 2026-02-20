# WB4U Contract Price Scraper — v1 Plan

> This file is the canonical reference for the project design.
> Consult it when context is lost or a new session starts.

---

## Purpose

Scrape ACM's public Tableau dashboard **Monitor Consumentenmarkt Energie** for Dutch energy contract prices. Normalize into atomic `PriceObservation` records, store locally (parquet/jsonl), and upsert to Railway Postgres for the WB4U frontend.

## Source

```
https://public.tableau.com/views/MonitorConsumentenmarktEnergie/Variabeleenvastecontracten
```

Publisher: ACM (Dutch energy regulator). Updated monthly on the 1st.

## Design Constraints

| Constraint | Rule |
|---|---|
| **Pricing semantics** | All-in prices only. Never reverse-engineer tax/network/VAT. |
| **Granularity** | Store native (monthly from ACM). Forward-fill to daily only if explicitly requested. Always produce monthly view. |
| **Scope v1** | electricity + gas + district_heating. Fixed + variable + hybrid. District heating/hybrid modeled as first-class. |
| **New providers** | Newly discovered providers/contracts → `pending_review` status. |
| **Extraction** | TableauScraper (primary). Playwright fallback only if needed. 700ms delay, 3 retries, polite UA. |
| **Execution** | GitHub Actions manual dispatch now, optional monthly cron later. |

## Target DB

Railway Postgres — same instance as WB4U. Env: `DATABASE_URL` / `DATABASE_PUBLIC_URL`. Tables prefixed `scraper_` to avoid collision with WB4U tables.

## WB4U Integration

WB4U's price loader: `WB4U/backend/python/app/data_access/load_tariffs.py`
Expected xlsx columns: `Company name`, `Contract type`, `Electricity price`, `Monthly Cost`, `Feed in specific`, `Feed-in`, `Gas price`, `Monthly gas cost`, `Duration`, `Deeplink`

The scraper creates a DB view `scraper_wb4u_provider_prices` that pivots atomic records into this exact shape.

---

## 1. Pipeline

```
EXTRACT → RAW STORE → NORMALIZE → VALIDATE → PUBLISH
```

1. **Extract**: Connect to Tableau, discover sheets, pull worksheet DataFrames.
2. **Raw store**: JSON per worksheet + `metadata.json` + SHA-256 hashes → `data/raw/tableau/{run_id}/`.
3. **Normalize**: Map Dutch columns → canonical fields, emit one `PriceObservation` per atomic observation.
4. **Validate**: Pandera schema + business-rule ranges + schema drift detection. Fail loud on breaking drift.
5. **Publish**: Local parquet/jsonl + upsert to `scraper_price_observations`. Register unknown providers in `scraper_provider_contracts` as `pending_review`.

---

## 2. Repo Structure

```
wb4u_webscrapper/
├── pyproject.toml
├── .env.example
├── .gitignore
├── PLAN.md                             ← you are here
├── README.md
├── alembic.ini
├── .github/workflows/scrape.yml
├── migrations/
│   ├── env.py
│   └── versions/001_initial_schema.py
├── src/wb4u_scraper/
│   ├── cli.py                          # Typer: run, validate, backfill, db-migrate
│   ├── config.py                       # pydantic-settings, WB4U_ prefix
│   ├── logging_setup.py                # structlog dev/json modes
│   ├── models/
│   │   ├── price_observation.py        # PriceObservation frozen dataclass
│   │   ├── run_metadata.py             # RunMetadata dataclass
│   │   └── db_models.py               # SQLAlchemy table definitions
│   ├── scraper/
│   │   ├── tableau_client.py           # TableauScraper wrapper + tenacity retry
│   │   ├── dashboard_navigator.py      # ACM sheet/storypoint discovery
│   │   ├── extraction.py               # Orchestrator: discover → drift → extract
│   │   └── fallback_playwright.py      # Playwright stub
│   ├── normalizer/
│   │   ├── field_mapper.py             # Dutch column → canonical field mapping
│   │   ├── transform.py                # Raw dicts → list[PriceObservation]
│   │   └── drift_detector.py           # Baseline comparison, DriftReport
│   ├── validator/
│   │   ├── rules.py                    # Biz rules: ranges, completeness
│   │   └── pandera_schemas.py          # Pandera DataFrameModel
│   ├── exporter/
│   │   ├── raw_exporter.py             # JSON snapshots + hashes
│   │   ├── local_exporter.py           # Parquet + JSONL to data/normalized/
│   │   └── db_publisher.py             # Upsert to Railway Postgres
│   └── utils/
│       ├── paths.py                    # Path resolution
│       └── hashing.py                  # SHA-256 content hashing
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   ├── unit/
│   └── integration/
├── data/                               # .gitignored
│   ├── raw/tableau/.gitkeep
│   └── normalized/.gitkeep
└── exports/excel/.gitkeep
```

---

## 3. Canonical Schema: `PriceObservation`

File: `src/wb4u_scraper/models/price_observation.py`

| Field | Type | Notes |
|---|---|---|
| `source` | str | default `tableau_acm_price_monitor` |
| `scraped_at_utc` | str | ISO timestamp |
| `valid_from` | str? | `YYYY-MM` or `YYYY-MM-DD` |
| `valid_to` | str? | nullable |
| `country` | str | `NL` |
| `provider_name` | str | |
| `contract_name` | str | |
| `contract_type` | str | `fixed\|variable\|dynamic\|hybrid\|model\|unknown` |
| `commodity` | str | `electricity\|gas\|district_heating` |
| `meter_direction` | str | `consumption\|feed_in` |
| `tou` | str | `on_peak\|off_peak\|flat\|unknown` |
| `unit` | str | `eur_per_kwh\|eur_per_m3\|eur_per_gj\|eur_per_month` |
| `value` | float | |
| `currency` | str | `EUR` |
| `is_all_in` | bool | default `True` |
| `price_includes` | str? | e.g. `energy+tax+vat` if known |
| `notes` | str | |
| `source_fields` | str | JSON blob of original Tableau fields |
| `content_hash` | str | SHA-256 of canonical key fields |

---

## 4. DB Schema

### `scraper_runs`

| Column | Type | Constraints |
|---|---|---|
| `run_id` | TEXT | **PK** |
| `started_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| `finished_at` | TIMESTAMPTZ | |
| `status` | TEXT | NOT NULL DEFAULT 'running' |
| `source_url` | TEXT | NOT NULL |
| `record_count` | INTEGER | |
| `raw_snapshot_hash` | TEXT | |
| `dashboard_structure` | JSONB | |
| `drift_report` | JSONB | |
| `error_message` | TEXT | |

### `scraper_price_observations`

| Column | Type | Constraints |
|---|---|---|
| `id` | BIGSERIAL | **PK** |
| `run_id` | TEXT | NOT NULL FK → scraper_runs |
| `content_hash` | TEXT | NOT NULL |
| `source` | TEXT | NOT NULL DEFAULT 'tableau_acm_price_monitor' |
| `scraped_at` | TIMESTAMPTZ | NOT NULL |
| `valid_from` | DATE | NOT NULL |
| `valid_to` | DATE | nullable |
| `country` | TEXT | NOT NULL DEFAULT 'NL' |
| `provider_name` | TEXT | NOT NULL |
| `contract_name` | TEXT | NOT NULL DEFAULT '' |
| `contract_type` | TEXT | NOT NULL |
| `commodity` | TEXT | NOT NULL |
| `meter_direction` | TEXT | NOT NULL |
| `tou` | TEXT | NOT NULL |
| `unit` | TEXT | NOT NULL |
| `value` | NUMERIC(12,6) | NOT NULL |
| `currency` | TEXT | NOT NULL DEFAULT 'EUR' |
| `is_all_in` | BOOLEAN | NOT NULL DEFAULT true |
| `price_includes` | TEXT | nullable |
| `notes` | TEXT | |
| `source_fields` | JSONB | |
| `review_status` | TEXT | NOT NULL DEFAULT 'active' |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |

**UNIQUE**: `(provider_name, contract_name, contract_type, commodity, meter_direction, tou, unit, valid_from)`

**Upsert**: `ON CONFLICT ... DO UPDATE SET value, content_hash, run_id, scraped_at, source_fields, updated_at WHERE content_hash differs`

### `scraper_provider_contracts`

| Column | Type | Constraints |
|---|---|---|
| `id` | BIGSERIAL | **PK** |
| `provider_name` | TEXT | NOT NULL |
| `contract_name` | TEXT | NOT NULL DEFAULT '' |
| `contract_type` | TEXT | NOT NULL |
| `commodity` | TEXT | NOT NULL |
| `first_seen_run` | TEXT | FK → scraper_runs |
| `first_seen_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() |
| `review_status` | TEXT | NOT NULL DEFAULT 'pending_review' |
| `reviewed_at` | TIMESTAMPTZ | |
| `notes` | TEXT | |

**UNIQUE**: `(provider_name, contract_name, contract_type, commodity)`

### Views

- `scraper_price_observations_monthly` — filters `review_status = 'active'`, adds `month` column
- `scraper_wb4u_provider_prices` — flat pivot matching WB4U's expected column names

---

## 5. Local Datasets

| Path | Contents |
|---|---|
| `data/raw/tableau/{run_id}/metadata.json` | Run metadata + dashboard structure + hashes |
| `data/raw/tableau/{run_id}/{worksheet}.json` | Verbatim rows per worksheet |
| `data/raw/tableau/{run_id}/content_hashes.json` | `{filename: sha256}` |
| `data/normalized/prices_{run_id}.parquet` | All PriceObservations |
| `data/normalized/prices_{run_id}.jsonl` | Same, line-delimited JSON |
| `data/normalized/prices_latest.parquet` | Symlink → most recent |
| `data/raw/tableau/dashboard_structure_baseline.json` | Drift detection baseline |
| `exports/excel/provider_prices_acm.xlsx` | WB4U drop-in format |
| `exports/excel/{type}_prices.xlsx` | Detailed workbook per contract type, tabs per year |

---

## 6. CLI Commands

```bash
wb4u-scraper run [--dry-run] [--skip-scrape] [--fallback]
wb4u-scraper validate [path]
wb4u-scraper backfill --start YYYY-MM --end YYYY-MM [--dry-run]
wb4u-scraper db-migrate
```

---

## 7. GitHub Actions

File: `.github/workflows/scrape.yml`

- **Trigger**: `workflow_dispatch` (manual) + optional `cron: "0 6 2 * *"` (2nd of month)
- **Inputs**: mode (run/validate/backfill), backfill_start, backfill_end, dry_run
- **Secrets**: `DATABASE_URL`
- **Artifacts**: raw snapshots, normalized data, Excel exports (90d retention)

---

## 8. Dutch → English Field Mapping

| Dutch | Canonical |
|---|---|
| Leverancier / Aanbieder | provider_name |
| Contractnaam / Product | contract_name |
| Contracttype / Contractsoort | contract_type |
| Tarief / Prijs | value |
| Energiesoort | commodity |
| Peildatum / Datum / Maand | valid_from |
| Vaste kosten / Vastrecht | fixed_cost_value |
| variabel → variable | vast → fixed |
| dynamisch → dynamic | hybride → hybrid |
| elektriciteit / stroom → electricity | aardgas / gas → gas |
| stadswarmte → district_heating | |

---

## 9. Implementation Status

| # | Module | Status |
|---|---|---|
| 1 | Project scaffold (pyproject.toml, dirs, git) | DONE |
| 2 | models/ (PriceObservation, RunMetadata, db_models) | DONE |
| 3 | config.py, logging_setup.py | DONE |
| 4 | utils/ (paths.py, hashing.py) | DONE |
| 5 | normalizer/field_mapper.py | DONE |
| 6 | normalizer/transform.py | DONE |
| 7 | validator/rules.py + pandera_schemas.py | DONE |
| 8 | normalizer/drift_detector.py | DONE |
| 9 | scraper/ (tableau_client, dashboard_navigator, extraction) | DONE |
| 10 | scraper/fallback_playwright.py (stub) | DONE |
| 11 | exporter/raw_exporter.py | DONE |
| 12 | exporter/local_exporter.py | DONE |
| 13 | exporter/db_publisher.py | DONE |
| 14 | cli.py | DONE |
| 15 | Alembic migration | DONE |
| 16 | tests/ (unit + integration, 51 passing) | DONE |
| 17 | .github/workflows/scrape.yml | DONE |
| 18 | README.md | DONE |

---

## 10. Assumptions

1. ACM dashboard exposes data via TableauScraper `getWorkbook()` → `worksheets[].data`. Column names are in Dutch.
2. ACM publishes monthly. `valid_from` = first of the month.
3. All-in prices. If breakdown columns exist, store each as `is_all_in = false`.
4. District heating: schema ready, v1 may produce zero records.
5. Hybrid contracts: detected when one contract name has different types per commodity.
6. Railway Postgres reachable from GitHub Actions (public endpoint).
7. No deeplinks or duration from ACM (NULL in DB).
8. Polite scraping: `WB4U-Scraper/0.1` UA, 700ms delay, 3 retries exponential backoff.
