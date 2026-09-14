"""
ENTSO-E Transparency Platform — day-ahead prices (12.1.D, documentType A44).

Docs: https://documenter.getpostman.com/view/7009892/2s93JtP3F6  ("12.1.D Energy Prices")
    GET https://web-api.tp.entsoe.eu/api
        securityToken = <your token>            (env ENTSOE_TOKEN, or ENTSOE_TOKEN=... in repo .env)
        documentType  = A44
        in_Domain     = out_Domain = 10YNL----------L      (NL bidding zone)
        periodStart / periodEnd = yyyyMMddHHmm in UTC     (max 1 year per request)
        contract_MarketAgreement.type = A01               (day-ahead; optional)
        offset        = 0,100,...  (max 100 TimeSeries per response -> paginate for > ~100 days)

Differences vs. the existing Entsoe/entsoe_daily_update.py parser, learned from the docs:
    * A44 responses use curveType **A03** ("variable sized blocks"): when consecutive prices are equal the
      repeated <Point>s are OMITTED (the doc sample has 95 points for a 96-slot day). Positions must be
      forward-filled to get a complete 15-minute grid. The old parser silently leaves those slots missing.
    * Since the SDAC 15-minute go-live (2025-10-01) NL is delivered as PT15M. The response can contain
      both PT15M and PT60M TimeSeries for the same interval; PT15M is preferred here and PT60M is only
      used when no 15-minute series covers a slot (pre-Oct-2025 history).
    * Prices are EUR/MWh in the XML; this script converts to EUR/kWh to match the other sources.
    * Error responses are an <Acknowledgement_MarketDocument> with a <Reason><text>; 401 = bad token.
    * Rate limit: 400 requests / minute per token (be polite, we do 1 request per range).

Usage:
    python test_entsoe_api.py                          # yesterday .. tomorrow
    python test_entsoe_api.py --start 2026-04-01 --end 2026-04-01 --compare-parquet
    python test_entsoe_api.py --start 2025-10-01 --end 2025-12-31 --save
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import xml.etree.ElementTree as ET

import pandas as pd
import requests

from common import DATA_DIR, LOCAL_TZ, NL_BIDDING_ZONE, REPO_ROOT, describe, get_entsoe_token, local_day_bounds_utc

BASE_URL = "https://web-api.tp.entsoe.eu/api"
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "wb4u-market-prices/0.1"

_ISO_DUR = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?$")


def parse_resolution(iso: str) -> pd.Timedelta:
    m = _ISO_DUR.match(iso or "")
    if not m:
        raise ValueError(f"Unsupported resolution {iso!r}")
    h, mi = (int(x) if x else 0 for x in m.groups())
    return pd.Timedelta(hours=h, minutes=mi)


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _ts_utc(text: str | None) -> pd.Timestamp:
    """ENTSO-E writes '2026-04-01T22:00Z'; be lenient about naive strings too."""
    ts = pd.Timestamp(text)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def parse_a44(xml_bytes: bytes) -> pd.DataFrame:
    """Parse a Publication_MarketDocument into rows (ts_utc, price_eur_mwh, resolution). A03 gaps are filled."""
    root = ET.fromstring(xml_bytes)
    if _strip_ns(root.tag) == "Acknowledgement_MarketDocument":
        reason = root.find(".//{*}Reason/{*}text")
        raise RuntimeError(f"ENTSO-E acknowledgement: {reason.text if reason is not None else 'unknown reason'}")

    rows: list[dict] = []
    for ts in root.iter():
        if _strip_ns(ts.tag) != "TimeSeries":
            continue
        curve = ts.findtext("{*}curveType") or "A01"
        for period in ts.findall("{*}Period"):
            res_txt = period.findtext("{*}resolution") or "PT60M"
            step = parse_resolution(res_txt)
            start = _ts_utc(period.findtext("{*}timeInterval/{*}start"))
            end = _ts_utc(period.findtext("{*}timeInterval/{*}end"))
            n_slots = int((end - start) / step)

            points: dict[int, float] = {}
            for pt in period.findall("{*}Point"):
                pos, price = pt.findtext("{*}position"), pt.findtext("{*}price.amount")
                if pos and price:
                    points[int(pos)] = float(price)

            last = None
            for pos in range(1, n_slots + 1):
                if pos in points:
                    last = points[pos]
                elif curve != "A03" or last is None:
                    continue  # genuinely missing
                rows.append({"ts_utc": start + (pos - 1) * step, "price_eur_mwh": last, "resolution": res_txt,
                             "filled": pos not in points})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # prefer PT15M over PT60M for the same slot; keep PT60M only where no 15-min series exists
    df["_prio"] = df["resolution"].map({"PT15M": 0, "PT30M": 1, "PT60M": 2}).fillna(3)
    df = df.sort_values(["ts_utc", "_prio"]).drop_duplicates("ts_utc", keep="first").drop(columns="_prio")
    return df.reset_index(drop=True)


def fetch_entsoe(start_utc: pd.Timestamp, end_utc: pd.Timestamp, token: str,
                 zone: str = NL_BIDDING_ZONE, offset: int = 0) -> tuple[pd.DataFrame, str]:
    params = {
        "securityToken": token,
        "documentType": "A44",
        "in_Domain": zone,
        "out_Domain": zone,
        "periodStart": start_utc.strftime("%Y%m%d%H%M"),
        "periodEnd": end_utc.strftime("%Y%m%d%H%M"),
        "contract_MarketAgreement.type": "A01",
        "offset": offset,
    }
    r = SESSION.get(BASE_URL, params=params, timeout=90)
    url = r.url.replace(token, "***")
    if r.status_code == 401:
        raise RuntimeError("HTTP 401 — securityToken rejected")
    r.raise_for_status()
    df = parse_a44(r.content)
    return df, url


def fetch_days(start_day: dt.date, end_day: dt.date, token: str, zone: str = NL_BIDDING_ZONE) -> pd.DataFrame:
    """Fetch whole NL calendar days [start_day, end_day] and return EUR/kWh rows with a `source` column."""
    s_utc, _ = local_day_bounds_utc(start_day)
    _, e_utc = local_day_bounds_utc(end_day)
    frames = []
    offset = 0
    while True:
        df, url = fetch_entsoe(s_utc, e_utc, token, zone, offset)
        print(f"  GET {url}\n      -> {len(df)} slots")
        if df.empty:
            break
        frames.append(df)
        # 1 TimeSeries per day; the API caps a response at 100 TimeSeries -> paginate
        if (end_day - start_day).days + 1 <= 100 * (offset // 100 + 1):
            break
        offset += 100
    if not frames:
        return pd.DataFrame(columns=["ts_utc", "price_eur_kwh", "resolution", "filled", "source"])
    out = pd.concat(frames, ignore_index=True).drop_duplicates("ts_utc").sort_values("ts_utc")
    out = out[(out["ts_utc"] >= s_utc) & (out["ts_utc"] < e_utc)]
    out["price_eur_kwh"] = out["price_eur_mwh"] / 1000.0
    out["source"] = "entsoe"
    return out[["ts_utc", "price_eur_kwh", "price_eur_mwh", "resolution", "filled", "source"]].reset_index(drop=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=dt.date.fromisoformat)
    p.add_argument("--end", type=dt.date.fromisoformat)
    p.add_argument("--zone", default=NL_BIDDING_ZONE)
    p.add_argument("--token", help="overrides env ENTSOE_TOKEN / .env")
    p.add_argument("--save", action="store_true", help="write data/test_entsoe_15min.parquet")
    p.add_argument("--compare-parquet", action="store_true",
                   help="compare with Entsoe/entsoe_prices_2026.parquet already in the repo")
    args = p.parse_args(argv)

    token = args.token or get_entsoe_token()
    if not token:
        print("ERROR: no ENTSO-E token. Set ENTSOE_TOKEN in the environment or put ENTSOE_TOKEN=... in the repo .env",
              file=sys.stderr)
        return 2

    today = dt.date.today()
    start = args.start or (today - dt.timedelta(days=1))
    end = args.end or (today + dt.timedelta(days=1))
    print(f"ENTSO-E A44 day-ahead  zone={args.zone}  |  {start} .. {end}\n")

    try:
        df = fetch_days(start, end, token, args.zone)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print(describe(df, "price_eur_kwh", "ELECTRICITY"))
    if not df.empty:
        print(f"resolutions: {df['resolution'].value_counts().to_dict()} | A03-filled slots: {int(df['filled'].sum())}")
        expected = pd.date_range(local_day_bounds_utc(start)[0], local_day_bounds_utc(end)[1], freq="15min", inclusive="left")
        missing = expected.difference(pd.DatetimeIndex(df["ts_utc"]))
        print(f"missing 15-min slots in range: {len(missing)}" + (f" (first: {missing[:3].tolist()})" if len(missing) else ""))
        s = df.head(6).copy()
        s["ts_local"] = s["ts_utc"].dt.tz_convert(LOCAL_TZ)
        print("\nSample rows (local time):")
        print(s[["ts_local", "price_eur_kwh", "price_eur_mwh", "resolution", "filled"]].to_string(index=False))

    if args.compare_parquet and not df.empty:
        ref_path = REPO_ROOT / "Entsoe" / "entsoe_prices_2026.parquet"
        ref = pd.read_parquet(ref_path)
        ref["ts_utc"] = pd.to_datetime(ref["ts_utc"], utc=True)
        m = df.merge(ref.rename(columns={"price": "ref_eur_kwh"}), on="ts_utc", how="left")
        print(f"\nCompared to {ref_path.name}: overlap={m['ref_eur_kwh'].notna().sum()} rows, "
              f"max |diff| = {(m['price_eur_kwh'] - m['ref_eur_kwh']).abs().max():.6f} EUR/kWh")

    if args.save and not df.empty:
        DATA_DIR.mkdir(exist_ok=True)
        df.to_parquet(DATA_DIR / "test_entsoe_15min.parquet", index=False)
        print(f"\nSaved to {DATA_DIR / 'test_entsoe_15min.parquet'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
