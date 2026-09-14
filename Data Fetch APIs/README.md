# Data Fetch APIs — market prices + weather (NL)

Exploration of three sources for Dutch day-ahead electricity (15-min) and gas (hourly/daily) prices, and of
KNMI weather data (outdoor temperature, global solar irradiance), plus daily updaters that keep parquet files
current and redraw charts.

## Findings (tested 2026-09-14)

| | ENTSO-E (official) | GridHub / Energiek | Frank Energie |
|---|---|---|---|
| Endpoint | `GET https://web-api.tp.entsoe.eu/api?documentType=A44…` | `GET https://mijn.energiek.nl/api/public/marketprice` | `POST https://graphql.frankenergie.nl/` |
| Auth | security token (`ENTSOE_TOKEN`) | **none** | **none** |
| Electricity resolution | **15-min** (PT15M since 2025-10-01), EUR/MWh | **15-min** (`frequency=QUARTER`) or hourly, EUR/kWh | hourly only, EUR/kWh |
| Gas | not available | hourly series, changes at 06:00 (gas day) | hourly series, same |
| History | years | 15-min from **2025-11-26**; hourly back to ≥2022; gas ≥2022 | ≥2025-01-01 |
| Tomorrow available | ~13:00 CET | ~13:00 CET + ≤1 h cache | ~13:00 CET |
| Rate limit | 400 req/min | **300 req/min** (`x-ratelimit-*` headers, 429 + Retry-After) | not hit |
| Quirks | `curveType A03`: repeated equal prices are *omitted* → must forward-fill (30 of 5,380 slots in Oct–Nov 2025); may mix PT15M+PT60M | mirrors ENTSO-E, so it shares ENTSO-E's holes; `frequency` must be omitted for GAS (422) | introspection disabled; only the notebook's fields are known |

**Consistency:** GridHub `QUARTER` == live ENTSO-E A44 == the repo's ENTSO-E parquet, to 0.000000 EUR/kWh
(288/288 slots, incl. the 92-slot DST day). GridHub `HOUR` == Frank hourly exactly; both == mean of the four
quarter-hours (≤5e-6 rounding). Gas GridHub == Frank (≤4e-6). So all three describe the same EPEX/TTF numbers.

**Known hole:** ENTSO-E has *no* NL day-ahead data for 2026-09-13 (`No matching data found`), and GridHub mirrors
that; Frank does have the day, so it is filled hourly there (`source=frank, resolution=PT60M`).

**GridHub response fields:** `withoutVat` = raw market price (use this), `withVat` = ×1.21,
`withTotalVat` = incl. VAT + energy tax (consumer all-in). Labels contain `"NU"` for the current slot, so
timestamps are derived from the position, not the label.

**Recommendation:** use GridHub `QUARTER` as the daily workhorse (keyless, 15-min, identical to ENTSO-E), ENTSO-E
as the preferred source whenever `ENTSOE_TOKEN` is set (it is the official record), and Frank as gap-filler
(hourly, expanded to 15-min and flagged `resolution=PT60M`). That is exactly what `daily_market_prices.py` does.

## KNMI weather — findings (tested 2026-09-14)

| | KNMI Data Platform (KDP) open-data API | Classic climatology service |
|---|---|---|
| Endpoint | `https://api.dataplatform.knmi.nl/open-data/v1/datasets/{ds}/versions/{v}/files` → `/files/{name}/url` | `POST https://www.daggegevens.knmi.nl/klimatologie/uurgegevens` (and `/daggegevens`) |
| Auth | `Authorization: <key>` — **`KNMI_API_KEY`** (free registered key: 1000 req/h). Docs publish a shared anonymous key (50 req/min shared) that hit "Rate Limit Exceeded" after 3 calls; EDR API is 403 for it | **none** |
| Data | dataset `10-minute-in-situ-meteorological-observations` v1.0: one netCDF (~170 KB, 56 stations, 97 vars) per 10 min; `ta` = air temp °C, `qg` = global radiation W/m², `Q1H` = J/cm² last hour | hourly `T` (0.1 °C, observed at END of the hour) and `Q` (J/cm² per hour → W/m² = ×2.778); daily `TG/TN/TX/Q`; 46 stations; 2.7 years in one 3.7 s POST, JSON |
| Latency / history | ~3–4 min latency; files kept since 2025-06-11 (~3 months) | validated data appears **1–2 days later** (on 14 Sep the last hour was 12 Sep 24:00 UTC); history back decades |
| Cost | 2 requests + 170 KB per 10-min file (144/day). **Parse with `netCDF4` in memory (0.05 s); `xarray.open_dataset` costs ~5 s/file** | 1 request per station-range |

Consistency check: KDP file 2026-09-12 13:00Z De Bilt `ta=21.1, Q1H=127.62` vs uurgegevens hour 13 `T=21.1, Q=128` → same
instruments; hour HH in the climatology = interval (HH-1, HH] UTC.

**Recommendation:** climatology service for history + daily validated update (keyless, one call), KDP 10-minute feed to
bridge the 1–2 day lag with near-real-time values. `daily_weather.py` does both and the chart shows the two joined.
Station 260 = De Bilt (national reference); 370 Eindhoven, 240 Schiphol, 344 Rotterdam, 280 Eelde, 380 Maastricht.

## Files

| File | Purpose |
|---|---|
| `test_entsoe_api.py` | A44 fetch with A03 forward-fill + PT15M preference; needs `ENTSOE_TOKEN` (env or repo `.env`). `--compare-parquet` checks against `Entsoe/entsoe_prices_2026.parquet`. Parser validated offline against the docs' sample XML. |
| `test_gridhub_api.py` | Energiek/GridHub electricity (QUARTER/HOUR) + gas, with rate-limit handling. |
| `test_frank_api.py` | Frank Energie GraphQL electricity + gas (hourly). |
| `compare_sources.py` | Prints max/mean abs differences between all sources for a date range. |
| `check_datasets.py` | Coverage/gap/duplicate report over every central parquet; exit 1 on problems. |
| `daily_market_prices.py` | **Daily prices job**: fetch → upsert parquet → chart. Idempotent; better source replaces worse. `--backfill-from` uses bulk 90-day ENTSO-E requests, then the per-day fallback chain only for incomplete days. |
| `test_knmi_api.py` | KNMI: hourly/daily climatology (keyless) + KDP 10-minute netCDF feed (`KNMI_API_KEY`). |
| `daily_weather.py` | **Daily weather job**: hourly (re-fetch last 5 days) + new 10-min files + derived daily → chart. `--backfill-from`, `--10min-since`. |
| `run_daily.ps1` | Runs both jobs with logging (`logs/`). `-WeatherStations "260,370"`, `-SkipWeather`. |
| `register_task.ps1` | Creates a Windows Task Scheduler job (07:30 and 14:30). `-Remove` to delete. |
| `common.py` | Shared helpers (tz, upsert, .env loading). |

## Central datasets (`data/`)

All files cover **2025-01-01 → now (+ tomorrow for prices)** and are extended by the daily job; re-runs are idempotent
(upsert on timestamp[, station], better source wins). `python check_datasets.py` prints coverage, gaps, duplicates
and sources per file and exits 1 if anything is missing — run it after any backfill.

Electricity before 2025-10-01 was an hourly market: those rows are the hourly ENTSO-E price repeated on the four
quarter-hours with `resolution=PT60M` (33,504 real 15-min rows, 26,300 expanded), so the 15-min file is one continuous
grid. Use `resolution` to tell them apart. Coverage as of 2026-09-14 (`check_datasets.py`): every file 0 missing, 0 dups.

One-off history load (already done; repeat only to rebuild):
```powershell
..\.venv\Scripts\python.exe daily_market_prices.py --backfill-from 2025-01-01 --no-chart   # ~4 min: bulk ENTSO-E + GridHub gas
..\.venv\Scripts\python.exe daily_weather.py --station 260 370 --backfill-from 2025-01-01  # ~10 s
..\.venv\Scripts\python.exe check_datasets.py
```

| File | Columns | Note |
|---|---|---|
| `electricity_prices_15min.parquet` | `ts_utc, price_eur_kwh, source, resolution` | 2025-01-01 → tomorrow, gap-free, DST-correct; ENTSO-E (PT60M expanded before 2025-10-01), Frank for 2026-09-13 |
| `electricity_prices_hourly.parquet` | `ts_utc, price_eur_kwh` | mean of the 4 quarter-hours |
| `gas_prices_hourly.parquet` | `ts_utc, price_eur_m3, source` | as served (steps at 06:00 local) |
| `gas_prices_daily.parquet` | `gas_day, price_eur_m3, calendar_day_mean_eur_m3, source` | price of gas day D = value at 06:00 on D |
| `market_prices_chart.png` | | 3 panels: 15-min last N days · daily mean/min-max · gas daily |
| `weather_hourly.parquet` | `ts_utc, station, temp_c, ghi_j_cm2, ghi_wm2, wind_ms, rh_pct, sunshine_h, source` | validated hourly, 2025-01-01 → (now − 1–2 days), stations 260 + 370; `ts_utc` = start of hour, `temp_c` observed at its end |
| `weather_10min.parquet` | `ts_utc, station, stationname, lat, lon, temp_c, ghi_wm2, ghi_j_cm2_1h, rh_pct, wind_ms, source` | near-real-time tail from where hourly ends |
| `weather_daily.parquet` | `date, station, temp_mean_c, temp_min_c, temp_max_c, ghi_kwh_m2_day, sunshine_h` | derived from hourly (local calendar days) |
| `weather_chart.png` | | temperature · irradiance (last N days, hourly + 10-min tail) · daily kWh/m² history |

## Usage

```powershell
cd "Data Fetch APIs"
..\.venv\Scripts\python.exe test_gridhub_api.py                   # today + tomorrow
..\.venv\Scripts\python.exe compare_sources.py --start 2026-04-01 --end 2026-04-03
..\.venv\Scripts\python.exe daily_market_prices.py                # last 3 days + tomorrow, then chart
..\.venv\Scripts\python.exe daily_market_prices.py --no-fetch --chart-days 30   # only redraw the chart
..\.venv\Scripts\python.exe test_knmi_api.py --station 260 370                  # weather: last 7 days + latest 10-min
..\.venv\Scripts\python.exe daily_weather.py --station 260 370 --backfill-from 2025-10-01

# automate (Windows Task Scheduler, runs run_daily.ps1 at 07:30 and 14:30)
powershell -ExecutionPolicy Bypass -File register_task.ps1
```

Secrets live in the repo-root `.env` (gitignored — never in `.env.example`): `ENTSOE_TOKEN` enables the ENTSO-E path,
`KNMI_API_KEY` the KDP 10-minute feed (without it the shared anonymous key is used, serially). Added to the venv:
`matplotlib` (charts), `netCDF4` (10-minute files); `xarray` is installed but not used (too slow for these files).
