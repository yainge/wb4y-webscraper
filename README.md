# WB4U Contract Price Scraper

Scrapes ACM's public Tableau dashboard ([Monitor Consumentenmarkt Energie](https://public.tableau.com/views/MonitorConsumentenmarktEnergie/Variabeleenvastecontracten)) for Dutch energy contract prices, normalizes into atomic `PriceObservation` records, and publishes to Railway Postgres.

See [PLAN.md](PLAN.md) for full architecture and design.

## Quick Start

```bash
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env  # edit DATABASE_URL
wb4u-scraper run --dry-run
```

## CLI Commands

```bash
# Full pipeline: scrape → normalize → validate → publish
wb4u-scraper run [--dry-run] [--skip-scrape] [--fallback]

# Validate a local dataset
wb4u-scraper validate [path/to/prices.parquet]

# Re-process historical snapshots
wb4u-scraper backfill --start 2024-01 --end 2025-01 [--dry-run]

# Apply DB migrations
wb4u-scraper db-migrate
```

## Pipeline

```
Tableau Public → TableauScraper → raw JSON snapshots
  → normalize (Dutch→English, type mapping)
  → validate (business rules + pandera schema)
  → export (parquet + jsonl locally)
  → upsert to Postgres (ON CONFLICT by natural key)
```

## Project Structure

```
src/wb4u_scraper/
├── models/           # PriceObservation, RunMetadata, SQLAlchemy models
├── scraper/          # TableauScraper client, dashboard navigator, extraction
├── normalizer/       # Field mapper, transform, drift detector
├── validator/        # Business rules, pandera schemas
├── exporter/         # Raw JSON, local parquet/jsonl, DB publisher
├── utils/            # Paths, hashing
├── config.py         # pydantic-settings (WB4U_ env prefix)
├── logging_setup.py  # structlog config
└── cli.py            # Typer CLI entrypoint
```

## Testing

```bash
# All tests
python -m pytest tests/ -v

# Unit tests only
python -m pytest tests/unit/ -v

# Integration tests (uses stored fixtures)
python -m pytest tests/integration/ -v -m integration
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | Railway Postgres connection string | — |
| `WB4U_TABLEAU_URL` | Tableau dashboard URL | ACM monitor URL |
| `WB4U_TABLEAU_DELAY_MS` | Polite delay between requests (ms) | `700` |
| `WB4U_LOG_LEVEL` | Logging level | `INFO` |
| `WB4U_LOG_JSON` | JSON log output (for CI) | `false` |

## GitHub Actions

Manual trigger via `workflow_dispatch`. Set `DATABASE_URL` as a repository secret.

```bash
gh workflow run scrape.yml
gh workflow run scrape.yml -f dry_run=true
```
