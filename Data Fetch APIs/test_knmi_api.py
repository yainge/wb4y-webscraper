"""
KNMI weather data — outdoor temperature and global solar irradiance.

Two routes, verified 2026-09-14:

1. KNMI Data Platform Open Data API (https://developer.dataplatform.knmi.nl/open-data-api)
       GET https://api.dataplatform.knmi.nl/open-data/v1/datasets/{dataset}/versions/{version}/files
       GET .../files/{filename}/url  -> temporaryDownloadUrl (presigned, no auth)
   Header:  Authorization: <API key>.  A public *anonymous* key is published in the docs (valid to 2027-08-01) but is
   SHARED: 50 req/min, 3000 req/h across all anonymous users — I hit "Rate Limit Exceeded" after 3 calls. For
   automation register a free key (KNMI_API_KEY in .env): 200 req/s, 1000 req/h. The EDR API is 403 for anonymous keys.
   Dataset "10-minute-in-situ-meteorological-observations" v1.0: one netCDF (~170 KB) per 10 min with ALL ~56 stations,
   97 variables (parse with netCDF4 in memory: 0.05 s; xarray.open_dataset takes ~5 s per file); we use  ta = air temperature 1.5 m [°C],  qg = global solar radiation mean [W/m²],
   Q1H = radiation last hour [J/cm²]. Files kept since 2025-06-11 (rolling ~3 months). Latency ~3-4 min.
   Cost: 2 requests per 10-min file  -> 288 requests/day  -> NOT the way to build history.

2. Classic climatology script service (no key, JSON, one POST for years of data)
       POST https://www.daggegevens.knmi.nl/klimatologie/uurgegevens   stns=260&vars=T:Q&start=YYYYMMDDHH&end=...&fmt=json
       POST https://www.daggegevens.knmi.nl/klimatologie/daggegevens   stns=260&vars=TG:TN:TX:Q&start=YYYYMMDD&end=...
   Hourly: T in 0.1 °C, Q in J/cm² per hour (-> W/m² = Q*10000/3600), "hour" 1..24 = interval ENDING at that UTC hour.
   Daily : TG/TN/TX in 0.1 °C, Q in J/cm² per day. 46 stations. Lag: validated data appears 1-2 days later
   (on 2026-09-14 evening the last available hour was 2026-09-12 24:00 UTC).

=> Use route 2 for the hourly history/daily update and route 1 only for "what is it right now" (last 10-min files).

Station codes (KDP uses '06'+code): 260 De Bilt, 240 Schiphol, 344 Rotterdam, 370 Eindhoven, 280 Eelde, 235 De Kooy,
290 Twenthe, 380 Maastricht, 310 Vlissingen, 330 Hoek van Holland.

Usage:
    python test_knmi_api.py                                # De Bilt: last 7 days hourly + daily, latest 10-min snapshot
    python test_knmi_api.py --station 370 --start 2026-06-01 --end 2026-06-30
    python test_knmi_api.py --no-10min                     # skip the KDP part (no key / rate-limited)
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import pandas as pd
import requests

from common import DATA_DIR, LOCAL_TZ, describe, load_env

CLIMATOLOGY_URL = "https://www.daggegevens.knmi.nl/klimatologie"
KDP_URL = "https://api.dataplatform.knmi.nl/open-data/v1"
KDP_DATASET, KDP_VERSION = "10-minute-in-situ-meteorological-observations", "1.0"
# Public anonymous key from the KNMI docs (shared rate limit; valid until 2027-08-01). Override with KNMI_API_KEY.
KDP_ANONYMOUS_KEY = (
    "eyJvcmciOiI1ZTU1NGUxOTI3NGE5NjAwMDEyYTNlYjEiLCJpZCI6IjUzYTg1ZDBhMmQ5YzRkYzJiYWNlNzQ4NTQ2Zjk4ODExIiwiaCI6Im11cm11cjEyOCJ9"
)
J_CM2_PER_HOUR_TO_W_M2 = 10_000 / 3_600  # J/cm² over one hour -> W/m² average

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "wb4u-market-prices/0.1"


def kdp_key() -> str:
    load_env()
    return os.getenv("KNMI_API_KEY") or KDP_ANONYMOUS_KEY


# --------------------------------------------------------------------------- route 2: climatology (history)
def fetch_hourly(stations: list[int] | str, start: dt.date, end: dt.date,
                 variables: tuple[str, ...] = ("T", "Q", "FH", "U", "SQ")) -> pd.DataFrame:
    """Hourly station data. Returns ts_utc = START of the hour, temp_c, ghi_wm2, plus raw columns."""
    stns = "ALL" if stations == "ALL" else ":".join(str(s) for s in stations)
    r = SESSION.post(f"{CLIMATOLOGY_URL}/uurgegevens", data={
        "stns": stns, "vars": ":".join(variables),
        "start": f"{start:%Y%m%d}01", "end": f"{end:%Y%m%d}24", "fmt": "json"}, timeout=120)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return pd.DataFrame(columns=["ts_utc", "station", "temp_c", "ghi_wm2"])
    df = pd.DataFrame(rows)
    # hour 1..24 = interval ending at that hour (UTC); store the interval start
    df["ts_utc"] = pd.to_datetime(df["date"], utc=True) + pd.to_timedelta(df["hour"] - 1, unit="h")
    df = df.rename(columns={"station_code": "station"})
    out = pd.DataFrame({"ts_utc": df["ts_utc"], "station": df["station"].astype(int)})
    if "T" in df:
        out["temp_c"] = pd.to_numeric(df["T"], errors="coerce") / 10.0
    if "Q" in df:
        out["ghi_j_cm2"] = pd.to_numeric(df["Q"], errors="coerce")
        out["ghi_wm2"] = out["ghi_j_cm2"] * J_CM2_PER_HOUR_TO_W_M2
    if "FH" in df:
        out["wind_ms"] = pd.to_numeric(df["FH"], errors="coerce") / 10.0
    if "U" in df:
        out["rh_pct"] = pd.to_numeric(df["U"], errors="coerce")
    if "SQ" in df:
        out["sunshine_h"] = pd.to_numeric(df["SQ"], errors="coerce").clip(lower=0) / 10.0  # -1 means <0.05 h
    out["source"] = "knmi_uurgegevens"
    return out.sort_values(["station", "ts_utc"]).reset_index(drop=True)


def fetch_daily(stations: list[int] | str, start: dt.date, end: dt.date,
                variables: tuple[str, ...] = ("TG", "TN", "TX", "Q", "SQ", "RH")) -> pd.DataFrame:
    stns = "ALL" if stations == "ALL" else ":".join(str(s) for s in stations)
    r = SESSION.post(f"{CLIMATOLOGY_URL}/daggegevens", data={
        "stns": stns, "vars": ":".join(variables),
        "start": f"{start:%Y%m%d}", "end": f"{end:%Y%m%d}", "fmt": "json"}, timeout=120)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return pd.DataFrame(columns=["date", "station"])
    df = pd.DataFrame(rows)
    out = pd.DataFrame({"date": pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize(),
                        "station": df["station_code"].astype(int)})
    for src, dst, scale in (("TG", "temp_mean_c", 0.1), ("TN", "temp_min_c", 0.1), ("TX", "temp_max_c", 0.1),
                            ("Q", "ghi_j_cm2_day", 1.0), ("SQ", "sunshine_h", 0.1), ("RH", "precip_mm", 0.1)):
        if src in df:
            out[dst] = pd.to_numeric(df[src], errors="coerce") * scale
    if "ghi_j_cm2_day" in out:
        out["ghi_kwh_m2_day"] = out["ghi_j_cm2_day"] * 10_000 / 3.6e6
    out["source"] = "knmi_daggegevens"
    return out.sort_values(["station", "date"]).reset_index(drop=True)


# --------------------------------------------------------------------------- route 1: KDP 10-minute (now)
def kdp_list_files(n: int = 6, newest_first: bool = True) -> list[dict]:
    r = SESSION.get(f"{KDP_URL}/datasets/{KDP_DATASET}/versions/{KDP_VERSION}/files",
                    params={"maxKeys": n, "sorting": "desc" if newest_first else "asc", "orderBy": "created"},
                    headers={"Authorization": kdp_key()}, timeout=30)
    if r.status_code == 429 or "Rate Limit" in r.text:
        raise RuntimeError("KDP rate limit exceeded (anonymous key is shared) — set KNMI_API_KEY to a registered key")
    r.raise_for_status()
    return r.json()["files"]


def kdp_fetch_10min(filename: str, variables: tuple[str, ...] = ("ta", "qg", "Q1H", "rh", "ff")) -> pd.DataFrame:
    """Download one 10-minute netCDF (all stations) and return a tidy frame with the requested variables.

    Parsed in memory with netCDF4 (~0.05 s); xarray.open_dataset on these 97-variable files costs ~5 s each.
    """
    import netCDF4  # pip install netCDF4
    import numpy as np

    r = SESSION.get(f"{KDP_URL}/datasets/{KDP_DATASET}/versions/{KDP_VERSION}/files/{filename}/url",
                    headers={"Authorization": kdp_key()}, timeout=30)
    if r.status_code == 429 or "Rate Limit" in r.text:
        raise RuntimeError("KDP rate limit exceeded (anonymous key is shared) — set KNMI_API_KEY to a registered key")
    r.raise_for_status()
    blob = SESSION.get(r.json()["temporaryDownloadUrl"], timeout=120).content

    ds = netCDF4.Dataset(filename, mode="r", memory=blob)
    try:
        tvar = ds["time"]
        when = pd.Timestamp(netCDF4.num2date(tvar[:], tvar.units, only_use_cftime_datetimes=False)[0]).tz_localize("UTC")
        cols = {"station": [str(x) for x in ds["station"][:]],
                "stationname": [str(x) for x in ds["stationname"][:]],
                "lat": np.ma.filled(ds["lat"][:], np.nan).astype(float),
                "lon": np.ma.filled(ds["lon"][:], np.nan).astype(float)}
        for v in variables:
            if v in ds.variables:
                arr = ds[v][:, 0]
                cols[v] = np.where(np.ma.getmaskarray(arr), np.nan, np.ma.filled(arr, np.nan)).astype(float)
    finally:
        ds.close()
    df = pd.DataFrame(cols)
    df["ts_utc"] = when
    # KDP ids are '06'+code for NL stations ('06260' -> 260, matches climatology codes); others (e.g. '78873') kept as-is
    df["station"] = df["station"].map(lambda s: int(s[2:]) if s.startswith("06") else int(s))
    df = df.rename(columns={"ta": "temp_c", "qg": "ghi_wm2", "Q1H": "ghi_j_cm2_1h", "rh": "rh_pct", "ff": "wind_ms"})
    df["source"] = "kdp_10min"
    return df.sort_values("station").reset_index(drop=True)


def kdp_latest(n_files: int = 6, stations: list[int] | None = None) -> pd.DataFrame:
    frames = [kdp_fetch_10min(f["filename"]) for f in kdp_list_files(n_files)]
    df = pd.concat(frames, ignore_index=True)
    if stations:
        df = df[df["station"].isin(stations)]
    return df.sort_values(["station", "ts_utc"]).reset_index(drop=True)


# --------------------------------------------------------------------------- main
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--station", type=int, nargs="+", default=[260], help="KNMI station code(s), default 260 De Bilt")
    p.add_argument("--start", type=dt.date.fromisoformat)
    p.add_argument("--end", type=dt.date.fromisoformat)
    p.add_argument("--no-10min", action="store_true", help="skip the KDP 10-minute part")
    p.add_argument("--save", action="store_true")
    args = p.parse_args(argv)

    today = dt.date.today()
    start = args.start or today - dt.timedelta(days=7)
    end = args.end or today
    print(f"KNMI weather  stations={args.station}  |  {start} .. {end}\n")

    hourly = fetch_hourly(args.station, start, end)
    print(describe(hourly, "temp_c", "HOURLY temp_c   "))
    if not hourly.empty:
        print(f"{'':18}ghi_wm2: max={hourly['ghi_wm2'].max():.0f} W/m2  daily-sum~{hourly['ghi_j_cm2'].sum() / (hourly['ts_utc'].dt.date.nunique()) * 1e4 / 3.6e6:.2f} kWh/m2/day")
        s = hourly[hourly["ghi_wm2"] > 0].tail(4).copy()
        s["ts_local"] = s["ts_utc"].dt.tz_convert(LOCAL_TZ)
        print(s[["ts_local", "station", "temp_c", "ghi_j_cm2", "ghi_wm2", "wind_ms", "rh_pct"]].to_string(index=False))
        print(f"{'':18}latest available hour: {hourly['ts_utc'].max()} (lag {(pd.Timestamp.now(tz='UTC') - hourly['ts_utc'].max())})")

    daily = fetch_daily(args.station, start, end)
    print(f"\nDAILY: {len(daily)} rows")
    if not daily.empty:
        print(daily.tail(4).to_string(index=False))

    if not args.no_10min:
        print("\nKDP 10-minute (latest 6 files = last hour):")
        try:
            now = kdp_latest(6, args.station)
            print(now[["ts_utc", "station", "stationname", "temp_c", "ghi_wm2", "ghi_j_cm2_1h", "rh_pct", "wind_ms"]].to_string(index=False))
        except Exception as exc:  # noqa: BLE001
            print(f"  skipped: {exc}", file=sys.stderr)

    if args.save:
        DATA_DIR.mkdir(exist_ok=True)
        hourly.to_parquet(DATA_DIR / "test_knmi_hourly.parquet", index=False)
        daily.to_parquet(DATA_DIR / "test_knmi_daily.parquet", index=False)
        print(f"\nSaved to {DATA_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
