# Tibber api — device data from the Tibber Data API

Scripts to pull data from **https://data-api.tibber.com** (REST, OpenAPI 3.1 at
`https://data-api.tibber.com/openapi/v1.json`, docs at `/docs/`, playground at `/playground/`) into parquet files,
following the same conventions as `Data Fetch APIs/` (`ts_utc`, `source`, idempotent upserts).

## What the Data API is (checked 2026-09-14)

| | |
|---|---|
| Scope | Third-party devices you paired in the Tibber app: EVs, EV chargers, thermostats / heat pumps / water heaters (NIBE, Mill, Ngenic, …), solar inverters, home batteries / energy systems — their static info, current state (*capabilities*), seldom-changing *attributes* and **history** at `quarterHour` / `hour` / `day` / `month`. Tibber Pulse / Watty meters only as a **live SSE stream** (W, kWh since midnight). |
| **Not** in scope | Prices and the home's hourly consumption/cost — those stay in the older GraphQL API (`https://api.tibber.com/v1-beta/gql`, personal access token). Smart-charging / optimisation schedules are not exposed. |
| Auth | **OAuth2 Authorization Code (+PKCE) only** — personal access tokens are explicitly not supported. Create a client at `https://thewall.tibber.com/clients/manage/`; access token ≈1 h (JWT, `Authorization: Bearer`), refresh token ≈30 d and may rotate. |
| Scopes | `openid profile email offline_access data-api-user-read data-api-homes-read` + per category `data-api-vehicles-read`, `data-api-chargers-read`, `data-api-thermostats-read`, `data-api-energy-systems-read`, `data-api-inverters-read`, `data-api-meters-read` (live stream). A device only appears if the token holds its category scope. |
| Endpoints | `GET /v1/homes` · `GET /v1/homes/{homeId}/devices` · `GET /v1/homes/{homeId}/devices/{deviceId}` · `GET /v1/homes/{homeId}/devices/{deviceId}/history?since\|until=…&resolution=…` · `GET /v1/homes/{homeId}/live-events/devices` · `GET /v1/homes/{homeId}/live-events?deviceId=…` |
| History | Cursor pagination: `since` ⇒ walk forward via `next`, `until` ⇒ walk backward via `prev`; no page-size control, no arbitrary slices. Minutes/seconds of `since`/`until` are truncated. `query.effectiveStart/End` show the clamped window (retention start … start of the current period — only *closed* periods are returned). Each item is `{time, data{…}}` with device-specific, possibly nested keys; `time` is in the home's time zone. `supportedHistory.resolutions` / `maxRetentionDays` on the device tell what is available. Data is immutable (gaps may rarely be back-filled). |
| Client rules | Mandatory `User-Agent: <App>/<Version> …`; full-jitter exponential backoff on `429`/`5xx` honouring `Retry-After`; never retry `400/401/403/404`. |
| Live stream | `text/event-stream`; events `measurement` (`LiveMeasurement`: `timestamp, power, powerProduction, min/avg/maxPower, accumulatedConsumption/Production, …`, all nullable), `ping` (~20 s), `stream_error` (`{code, transient, retryAfter?, deviceId?}`; `evicted` = another connection took the home's single slot). Max 5 devices / connection, 1 connection / home. |

## What this account exposes (checked 2026-09-14)

Home `7ea61717-e440-4067-94f3-b4d59110d259` ("Huis", in `.env` as `TIBBER_HOME_ID`) has two devices, **both
state-only** (`supportedHistory` empty, so `history`/`update` have nothing to fetch) and no streamable meter:

| Device | Capabilities (current state) |
|---|---|
| Easee Home 2.1 charger (`ZWFzZWUg…`) | `grid.phaseCount`, `connector.status`, `charging.status`, `charging.current.max` (A), `charging.current.offlineFallback` (A) |
| Volkswagen ID.4 (`dm9sa3N3…`) | `storage.stateOfCharge` (%), `storage.targetStateOfCharge` (%), `range.remaining` (m), `connector.status`, `charging.status` |

So the only way to get a time series is to **poll**: `fetch_tibber.py snapshot` appends every capability value of
every device to `data/device_state.parquet` (long format, upsert on `device_id, capability, ts_utc`) — run it on a
schedule (e.g. every 15 min via Task Scheduler, like `Data Fetch APIs/register_task.ps1`). `lastSeen` shows when
Tibber itself last polled the device (the ID.4 was refreshed minutes before; the charger hours before), so a
snapshot interval much shorter than that only repeats values.

Client `TestingAPI2` (2026-09-14) was created with every category scope; after login the token holds
`data-api-homes/vehicles/chargers/thermostats/energy-systems/inverters/meters-read`, yet `/v1/homes/{id}/devices`
still returns only the charger and the ID.4 and `/live-events/devices` is empty. So the solar inverter is either
not paired as a device in the Tibber app or its brand is one of the integrations Tibber has "not yet" exposed (there
is no public list; watch the changelog). Until it appears, solar is only visible as grid feed-in via the GraphQL
`production` series. The token exchange **requires the client secret** even with PKCE (FAQ: "public flows without
a secret are not supported").

## Files

| File | Purpose |
|---|---|
| `tibber_auth.py` | `login` (opens the browser, PKCE + `state`, local callback on `http://localhost:8765/callback`), `refresh`, `status`. Stores tokens in `tokens.json` (gitignored). `get_access_token()` auto-refreshes; `TIBBER_ACCESS_TOKEN` in the environment overrides it (e.g. a token copied from the Playground). |
| `tibber_client.py` | `TibberDataClient`: mandatory User-Agent, Bearer auth with one automatic refresh on 401, full-jitter retry on 429/5xx, `homes/devices/device`, `history()` generator that follows `next`/`prev` links, `stream_live()` SSE generator. |
| `fetch_tibber.py` | CLI: `homes`, `devices [--save]`, `device <id> [--json]`, `history <id> --resolution … [--since\|--until]`, `update [--backfill] [--resolution …]` (incremental daily job), `snapshot` (poll current state), `live [--count N]`. |
| `tibber_graphql.py` | **Historic consumption / production / prices** from the GraphQL API (`api.tibber.com/v1-beta/gql`, `TIBBER_TOKEN` personal access token): `info`, `consumption`, `production`, `prices` (`--resolution`, `--since`), `update` (hourly, incremental). Pages backwards with `last`/`before` until `--since` or the start of history. Queries validated against the live schema by introspection. |
| `plot_tibber.py` | Chart of the GraphQL history → `data/tibber_chart.png`: daily kWh in/out, daily cost/profit, hourly price (total vs market), last 7 days hourly. |
| `common.py` | `.env` loading, `upsert_parquet`, `describe`. |

## Outputs (`data/`, gitignored)

| File | Columns |
|---|---|
| `devices_<home>.json` | full device details (info, supportedHistory, status, attributes, capabilities) |
| `history_<brand-model-id>_<resolution>.parquet` | `ts_utc, ts_local, home_id, device_id, resolution, source` + the flattened `data.*` keys of that device (nested keys joined with `.`, e.g. `energyFlow.gridImport`) |
| `device_state.parquet` | `ts_utc, home_id, device_id, device, capability, value_num, value_str, unit, last_seen, source` — one row per device × capability per `snapshot` run |
| `consumption_<res>.parquet` / `production_<res>.parquet` | `ts_utc, ts_end_utc, home_id, consumption_kwh\|production_kwh, cost\|profit, unit_price, unit_price_vat, currency, source` (GraphQL) |
| `prices_<res>.parquet` | `ts_utc, home_id, total, energy, tax, level, currency, source` (GraphQL, `QUARTER_HOURLY`/`HOURLY`/`DAILY`) |

`update` resumes from the last stored `ts_utc` per file (minus a small overlap) and upserts on `(device_id, ts_utc)`,
so it is safe to run daily; `--backfill` re-pulls everything the API retains (`since=2000-01-01` is clamped to the
first record).

## Usage

```powershell
cd "Tibber api"

# one-off: create an OAuth client at https://thewall.tibber.com/clients/manage/
#   redirect URI  http://localhost:8765/callback , tick the scopes you need
#   put TIBBER_CLIENT_ID and TIBBER_CLIENT_SECRET in the repo-root .env (secret is mandatory)
..\.venv\Scripts\python.exe tibber_auth.py login             # browser login -> tokens.json
..\.venv\Scripts\python.exe tibber_auth.py status

..\.venv\Scripts\python.exe fetch_tibber.py homes
..\.venv\Scripts\python.exe fetch_tibber.py devices --save   # what is paired + which resolutions/retention
..\.venv\Scripts\python.exe fetch_tibber.py device <deviceId>
..\.venv\Scripts\python.exe fetch_tibber.py history <deviceId> --resolution hour --since 2026-09-01
..\.venv\Scripts\python.exe fetch_tibber.py update --backfill                 # first full load
..\.venv\Scripts\python.exe fetch_tibber.py update                            # daily incremental
..\.venv\Scripts\python.exe fetch_tibber.py snapshot                          # poll current state -> device_state.parquet
..\.venv\Scripts\python.exe fetch_tibber.py live --count 10                   # Pulse/Watty live power

# historic consumption / production / prices (GraphQL API, needs TIBBER_TOKEN in .env)
..\.venv\Scripts\python.exe tibber_graphql.py info
..\.venv\Scripts\python.exe tibber_graphql.py consumption --resolution HOURLY --since 2025-01-01
..\.venv\Scripts\python.exe tibber_graphql.py prices --resolution QUARTER_HOURLY --since 2026-01-01
..\.venv\Scripts\python.exe tibber_graphql.py update                            # hourly, incremental
..\.venv\Scripts\python.exe plot_tibber.py                                     # -> data/tibber_chart.png
```

Everything runs on the packages already in the venv (`requests`, `pandas`, `pyarrow`, `python-dotenv`).

## Notes / gotchas

* If `devices` returns an empty list, the token most likely lacks the category scope (add it to the client and
  run `login` again — new scopes need a fresh consent) or nothing of that category is paired in the app.
* `history` only returns *closed* periods: the current hour/day/month is missing until it completes — go one
  resolution finer and aggregate yourself if you need the running period.
* Thermostat `day` history is a dynamic aggregate (average temperature only); energy-system `storage` series
  exist only at `quarterHour`/`hour`, and `energyFlow`/`storage`/`solar` are stitched together so holes can occur.
* Home consumption (kWh/h), production and prices are **not** in the Data API — `tibber_graphql.py` fetches them
  from the GraphQL API with a personal access token (https://developer.tibber.com/settings/access-token →
  `TIBBER_TOKEN` in `.env`). Verified 2026-09-14 on this home: hourly consumption / production / prices from the
  contract start (2026-07-14) onward, 15-min prices too. The last ~22 hours of consumption/production are `NaN`
  until the smart-meter readings arrive (prices are already there); `update` re-fetches the last 2 days so those
  fill in on the next run. Tibber's `energy` price equals the repo's market price (`Data Fetch APIs`) to 1e-6
  EUR/kWh; `total` = `energy` + `tax` (energy tax + VAT) = `unit_price` on the consumption rows.
