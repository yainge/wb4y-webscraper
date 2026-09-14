"""
Frank Energie public GraphQL API (the one already used in "Gas prices api/Frank_prices_api.ipynb").

    POST https://graphql.frankenergie.nl/
    query MarketPrices { marketPrices(date: "YYYY-MM-DD") { electricityPrices {...} gasPrices {...} } }

No authentication. Introspection is disabled ("Graphql validation error"), so only the fields
used in the notebook are known: from, till, marketPrice, marketPriceTax, sourcingMarkupPrice,
energyTaxPrice, perUnit.

Findings (verified 2026-09-14):
    * electricity: HOURLY only (24 rows/day, 'from'/'till' in UTC). marketPrice == GridHub HOUR withoutVat
      == mean of the four ENTSO-E 15-min prices. No 15-minute resolution available here.
    * gas: 24 hourly rows/day, value changes at 06:00 local (gas day). Tomorrow returns 6 rows until
      the next gas day-ahead price is published.
    * history back to at least 2025-01-01 (the notebook pulled 2025-01-01 .. 2026-04-21 without gaps).
    * marketPriceTax = 21% VAT on marketPrice; energyTaxPrice / sourcingMarkupPrice are Frank-specific
      consumer components -> only marketPrice is the "market" price.

Usage:
    python test_frank_api.py                       # today + tomorrow
    python test_frank_api.py --start 2026-09-01 --end 2026-09-14 --save
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

import pandas as pd
import requests

from common import DATA_DIR, LOCAL_TZ, daterange, describe

GRAPHQL_URL = "https://graphql.frankenergie.nl/"
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "wb4u-market-prices/0.1"

# date is inlined (like the notebook) because introspection is off and the scalar type of `date` is unknown
QUERY = """
query MarketPrices {
  marketPrices(date: "%s") {
    electricityPrices { from till marketPrice marketPriceTax sourcingMarkupPrice energyTaxPrice perUnit }
    gasPrices         { from till marketPrice marketPriceTax sourcingMarkupPrice energyTaxPrice perUnit }
  }
}
"""


def fetch_frank_raw(day: dt.date) -> dict:
    r = SESSION.post(GRAPHQL_URL, json={"query": QUERY % day.isoformat()}, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if payload.get("errors"):
        raise RuntimeError(f"Frank Energie API error: {payload['errors'][0].get('message', payload['errors'])}")
    return payload["data"]["marketPrices"]


def _to_frame(rows: list[dict], value_col: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["ts_utc", "ts_end_utc", value_col, "source", "resolution"])
    df = pd.DataFrame(rows)
    out = pd.DataFrame(
        {
            "ts_utc": pd.to_datetime(df["from"], utc=True),
            "ts_end_utc": pd.to_datetime(df["till"], utc=True),
            value_col: pd.to_numeric(df["marketPrice"], errors="coerce"),
            "vat": pd.to_numeric(df["marketPriceTax"], errors="coerce"),
            "sourcing_markup": pd.to_numeric(df["sourcingMarkupPrice"], errors="coerce"),
            "energy_tax": pd.to_numeric(df["energyTaxPrice"], errors="coerce"),
            "unit": df["perUnit"],
            "source": "frank",
        }
    )
    out["resolution"] = "PT60M"
    return out


def fetch_day(day: dt.date) -> tuple[pd.DataFrame, pd.DataFrame]:
    mp = fetch_frank_raw(day)
    return (
        _to_frame(mp.get("electricityPrices") or [], "price_eur_kwh"),
        _to_frame(mp.get("gasPrices") or [], "price_eur_m3"),
    )


def fetch_range(start: dt.date, end: dt.date) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    elec, gas, missing = [], [], []
    for day in daterange(start, end):
        try:
            e, g = fetch_day(day)
        except (requests.RequestException, RuntimeError) as exc:
            print(f"  {day}: {exc}", file=sys.stderr)
            missing.append(day.isoformat())
            continue
        if e.empty and g.empty:
            missing.append(day.isoformat())
        elec.append(e)
        gas.append(g)
    e_all = pd.concat(elec, ignore_index=True) if elec else pd.DataFrame()
    g_all = pd.concat(gas, ignore_index=True) if gas else pd.DataFrame()
    return e_all, g_all, missing


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", type=dt.date.fromisoformat)
    p.add_argument("--start", type=dt.date.fromisoformat)
    p.add_argument("--end", type=dt.date.fromisoformat)
    p.add_argument("--save", action="store_true")
    args = p.parse_args(argv)

    today = dt.date.today()
    if args.start or args.end:
        start, end = args.start or args.end, args.end or args.start
    elif args.date:
        start = end = args.date
    else:
        start, end = today, today + dt.timedelta(days=1)

    print(f"Frank Energie GraphQL  |  {start} .. {end}\n")
    elec, gas, missing = fetch_range(start, end)
    print(describe(elec, "price_eur_kwh", "ELECTRICITY (hourly)"))
    print(describe(gas, "price_eur_m3", "GAS (hourly)        "))
    if missing:
        print(f"   missing/empty days: {missing}")

    if not elec.empty:
        s = elec.head(4).copy()
        s["ts_local"] = s["ts_utc"].dt.tz_convert(LOCAL_TZ)
        print("\nSample electricity rows (local time):")
        print(s[["ts_local", "price_eur_kwh", "vat", "sourcing_markup", "energy_tax", "unit"]].to_string(index=False))
    if not gas.empty:
        g = gas.copy()
        g["ts_local"] = g["ts_utc"].dt.tz_convert(LOCAL_TZ)
        changes = g.loc[g["price_eur_m3"].diff().fillna(0) != 0, "ts_local"].dt.strftime("%Y-%m-%d %H:%M").tolist()
        print(f"\nGas price change moments (local): {changes[:8]}{' ...' if len(changes) > 8 else ''}")

    if args.save:
        DATA_DIR.mkdir(exist_ok=True)
        elec.to_parquet(DATA_DIR / "test_frank_electricity_hourly.parquet", index=False)
        gas.to_parquet(DATA_DIR / "test_frank_gas_hourly.parquet", index=False)
        print(f"\nSaved to {DATA_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
