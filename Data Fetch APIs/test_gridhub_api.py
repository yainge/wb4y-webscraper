"""
GridHub "CP Public" market-price endpoint (used by Energiek's customer portal).

Docs: https://gridhub.stoplight.io/docs/gridhub-external/ofi9onz8u60v7-get-marketpricechart
Spec (OpenAPI, extracted from Stoplight):
    GET https://{myURL}/api/public/marketprice
        marketSegment = ELECTRICITY | GAS          (required)
        date          = YYYY-MM-DD                 (required, local NL calendar day)
        frequency     = QUARTER | HOUR             (required for ELECTRICITY, must be OMITTED for GAS -> 422)
    No authentication. "myURL" is the supplier's mijn-portal; for Energiek that is mijn.energiek.nl.

Response: {"withoutVat": {"mean", "series": [..], "labels": [{"label","tooltip","color"}]},
           "withVat": {...}, "withTotalVat": {...}}
    withoutVat   = raw day-ahead market price, EUR/kWh (elec) or EUR/m3 (gas)  -> identical to ENTSO-E / Frank
    withVat      = withoutVat * 1.21
    withTotalVat = withVat + energy tax incl. VAT (the "all-in" consumer price the portal shows)

Findings (verified 2026-09-14):
    * ELECTRICITY QUARTER: 96 points/day (92 / 100 on DST days) — exactly equal to ENTSO-E A44 NL 15-min prices.
      15-minute history only from 2025-11-26; HOUR history goes back to at least 2022.
    * GAS: 24 hourly points but the value only changes at 06:00 local (gas day D = 06:00 D -> 06:00 D+1).
      Tomorrow's gas therefore only returns 6 points (00:00-06:00 = today's gas day) until the next day-ahead is set.
    * Tomorrow's electricity is available after the EPEX day-ahead auction (~13:00 CET) + up to 1h cache delay.
    * Occasionally a day is simply missing (200 with empty series) — 2026-09-13 was missing while neighbours were fine.
      A production fetcher should fall back to another source for such days.

Usage:
    python test_gridhub_api.py                     # today + tomorrow, elec (QUARTER + HOUR) and gas
    python test_gridhub_api.py --date 2026-04-01
    python test_gridhub_api.py --start 2026-09-01 --end 2026-09-14 --save
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

import pandas as pd
import requests

from common import DATA_DIR, LOCAL_TZ, daterange, describe

DEFAULT_HOST = "mijn.energiek.nl"
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "wb4u-market-prices/0.1"


RATE_LIMIT_HEADROOM = 3  # pause when x-ratelimit-remaining drops below this (limit is 300 per minute)


def fetch_gridhub_raw(segment: str, day: dt.date, frequency: str | None, host: str = DEFAULT_HOST) -> dict:
    params = {"marketSegment": segment, "date": day.isoformat()}
    if frequency:
        params["frequency"] = frequency
    for attempt in range(4):
        r = SESSION.get(f"https://{host}/api/public/marketprice", params=params, timeout=30)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 60)) + 1
            print(f"  gridhub 429 rate-limited, sleeping {wait}s (attempt {attempt + 1})", file=sys.stderr)
            time.sleep(wait)
            continue
        r.raise_for_status()
        remaining = r.headers.get("x-ratelimit-remaining")
        if remaining is not None and int(remaining) < RATE_LIMIT_HEADROOM:
            print("  gridhub rate-limit headroom exhausted, sleeping 61s", file=sys.stderr)
            time.sleep(61)
        return r.json()
    r.raise_for_status()
    return r.json()


def _series_to_frame(payload: dict, day: dict | dt.date, freq: str, value_col: str, source: str) -> pd.DataFrame:
    """Build a tz-aware frame. Index-based (not label-based): labels contain 'NU' for the current slot."""
    without = payload.get("withoutVat") or {}
    series = without.get("series") or []
    if not series:
        return pd.DataFrame(columns=["ts_utc", value_col, "source", "resolution"])
    vat = list((payload.get("withVat") or {}).get("series") or [])
    allin = list((payload.get("withTotalVat") or {}).get("series") or [])
    series = list(series)
    # DST fall-back day has 25 local hours but GAS returns 24 wall-clock values (the repeated 02:00 is not
    # duplicated). Gas is constant within its gas day, so pad the missing 25th hour with the last value.
    day_start = pd.Timestamp(day).tz_localize(LOCAL_TZ)
    expected = int(((pd.Timestamp(day) + pd.Timedelta(days=1)).tz_localize(LOCAL_TZ) - day_start) / pd.Timedelta(freq if freq != "h" else "1h"))
    if freq == "h" and len(series) == 24 and expected == 25:
        series.append(series[-1])
        vat.append(vat[-1] if vat else float("nan"))
        allin.append(allin[-1] if allin else float("nan"))
    idx = pd.date_range(day_start, periods=len(series), freq=freq)
    return pd.DataFrame(
        {
            "ts_utc": idx.tz_convert("UTC"),
            value_col: pd.to_numeric(pd.Series(series), errors="coerce").to_numpy(),
            "price_incl_vat": pd.to_numeric(pd.Series(vat), errors="coerce").reindex(range(len(series))).to_numpy(),
            "price_all_in": pd.to_numeric(pd.Series(allin), errors="coerce").reindex(range(len(series))).to_numpy(),
            "source": source,
            "resolution": "PT15M" if freq == "15min" else "PT60M",
        }
    )


def fetch_electricity(day: dt.date, quarter: bool = True, host: str = DEFAULT_HOST) -> pd.DataFrame:
    payload = fetch_gridhub_raw("ELECTRICITY", day, "QUARTER" if quarter else "HOUR", host)
    return _series_to_frame(payload, day, "15min" if quarter else "h", "price_eur_kwh", "gridhub")


def fetch_gas(day: dt.date, host: str = DEFAULT_HOST) -> pd.DataFrame:
    payload = fetch_gridhub_raw("GAS", day, None, host)
    return _series_to_frame(payload, day, "h", "price_eur_m3", "gridhub")


def fetch_range(fetch_fn, start: dt.date, end: dt.date, **kw) -> tuple[pd.DataFrame, list[str]]:
    frames, missing = [], []
    for day in daterange(start, end):
        try:
            df = fetch_fn(day, **kw)
        except requests.RequestException as exc:
            print(f"  {day}: HTTP error {exc}", file=sys.stderr)
            missing.append(day.isoformat())
            continue
        if df.empty:
            missing.append(day.isoformat())
        frames.append(df)
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return out, missing


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--date", type=dt.date.fromisoformat, help="single day (default: today and tomorrow)")
    p.add_argument("--start", type=dt.date.fromisoformat)
    p.add_argument("--end", type=dt.date.fromisoformat)
    p.add_argument("--save", action="store_true", help="write results to data/test_gridhub_*.parquet")
    args = p.parse_args(argv)

    today = dt.date.today()
    if args.start or args.end:
        start, end = args.start or args.end, args.end or args.start
    elif args.date:
        start = end = args.date
    else:
        start, end = today, today + dt.timedelta(days=1)

    print(f"GridHub public marketprice @ {args.host}  |  {start} .. {end}\n")

    elec_q, miss_q = fetch_range(fetch_electricity, start, end, quarter=True, host=args.host)
    print(describe(elec_q, "price_eur_kwh", "ELECTRICITY QUARTER"))
    if miss_q:
        print(f"   missing/empty days: {miss_q}")

    elec_h, miss_h = fetch_range(fetch_electricity, start, end, quarter=False, host=args.host)
    print(describe(elec_h, "price_eur_kwh", "ELECTRICITY HOUR   "))
    if miss_h:
        print(f"   missing/empty days: {miss_h}")

    gas, miss_g = fetch_range(fetch_gas, start, end, host=args.host)
    print(describe(gas, "price_eur_m3", "GAS (hourly)       "))
    if miss_g:
        print(f"   missing/empty days: {miss_g}")

    if not elec_q.empty and not elec_h.empty:
        # hourly value should be the mean of its four quarter-hours
        q_hourly = (
            elec_q.set_index("ts_utc")["price_eur_kwh"].resample("h").mean().rename("quarter_mean")
        )
        cmp = elec_h.set_index("ts_utc")["price_eur_kwh"].to_frame("hour").join(q_hourly, how="inner")
        print(f"\nHOUR vs mean(QUARTER): max |diff| = {(cmp['hour'] - cmp['quarter_mean']).abs().max():.6f} EUR/kWh")

    if not gas.empty:
        g = gas.copy()
        g["ts_local"] = g["ts_utc"].dt.tz_convert(LOCAL_TZ)
        changes = g.loc[g["price_eur_m3"].diff().fillna(0) != 0, "ts_local"].dt.strftime("%Y-%m-%d %H:%M").tolist()
        print(f"Gas price change moments (local): {changes[:8]}{' ...' if len(changes) > 8 else ''}")

    print("\nSample electricity 15-min rows (local time):")
    if not elec_q.empty:
        s = elec_q.head(6).copy()
        s["ts_local"] = s["ts_utc"].dt.tz_convert(LOCAL_TZ)
        print(s[["ts_local", "price_eur_kwh", "price_incl_vat", "price_all_in"]].to_string(index=False))

    if args.save:
        DATA_DIR.mkdir(exist_ok=True)
        elec_q.to_parquet(DATA_DIR / "test_gridhub_electricity_15min.parquet", index=False)
        elec_h.to_parquet(DATA_DIR / "test_gridhub_electricity_hourly.parquet", index=False)
        gas.to_parquet(DATA_DIR / "test_gridhub_gas_hourly.parquet", index=False)
        print(f"\nSaved to {DATA_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
