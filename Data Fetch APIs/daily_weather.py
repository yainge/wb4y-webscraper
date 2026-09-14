"""
Daily KNMI weather updater: outdoor temperature + global solar irradiance -> parquet -> chart.

    hourly  (history, validated)   : daggegevens.knmi.nl uurgegevens, no key, one POST per station-range.
                                     Re-fetches the last --days-back days every run because validated data
                                     appears with a 1-2 day lag.
    10-min  (near-real-time)       : KNMI Data Platform 10-minute netCDF feed, KNMI_API_KEY from .env
                                     (falls back to the shared anonymous key). Fetches only files newer than
                                     the last stored timestamp, capped at --max-10min-files per run
                                     (2 API requests per file; registered key = 1000 req/h).
    daily   (derived)              : from hourly -> mean/min/max temp, GHI kWh/m2/day.

Outputs (./data):
    weather_hourly.parquet   ts_utc (start of hour, UTC), station, temp_c (observed at END of the hour),
                             ghi_j_cm2, ghi_wm2 (hour mean), wind_ms, rh_pct, sunshine_h, source
    weather_10min.parquet    ts_utc, station, stationname, temp_c, ghi_wm2, ghi_j_cm2_1h, rh_pct, wind_ms, source
    weather_daily.parquet    date, station, temp_mean_c, temp_min_c, temp_max_c, ghi_kwh_m2_day, sunshine_h
    weather_chart.png        temperature (last N days: hourly + 10-min tail), irradiance (same window),
                             daily GHI kWh/m2 over the full history

Usage:
    python daily_weather.py                               # De Bilt, last 5 days hourly + new 10-min files, chart
    python daily_weather.py --station 260 370 --backfill-from 2025-10-01
    python daily_weather.py --no-10min                     # climatology only
    python daily_weather.py --no-fetch --chart-days 30
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

import pandas as pd

import test_knmi_api as knmi
from common import DATA_DIR, LOCAL_TZ, describe, upsert_parquet

W_HOURLY = DATA_DIR / "weather_hourly.parquet"
W_10MIN = DATA_DIR / "weather_10min.parquet"
W_DAILY = DATA_DIR / "weather_daily.parquet"
CHART = DATA_DIR / "weather_chart.png"
KEY = ["ts_utc", "station"]


def update_hourly(stations: list[int], start: dt.date, end: dt.date) -> pd.DataFrame:
    new = knmi.fetch_hourly(stations, start, end)
    if new.empty:
        print("  hourly: nothing returned")
        return pd.read_parquet(W_HOURLY) if W_HOURLY.exists() else new
    return upsert_parquet(new, W_HOURLY, key=KEY)


def update_10min(stations: list[int], max_files: int, since: pd.Timestamp | None = None, workers: int = 6) -> pd.DataFrame:
    """Fetch 10-minute files newer than the last stored one; on the first run start where validated hourly data ends."""
    if since is not None:
        last_ts = since
    elif W_10MIN.exists():
        last_ts = pd.to_datetime(pd.read_parquet(W_10MIN)["ts_utc"], utc=True).max()
    elif W_HOURLY.exists():
        last_ts = pd.to_datetime(pd.read_parquet(W_HOURLY)["ts_utc"], utc=True).max() + pd.Timedelta(hours=1)
    else:
        last_ts = pd.Timestamp.now(tz="UTC").floor("10min") - pd.Timedelta(hours=24)
    after = f"KMDS__OPER_P___10M_OBS_L2_{last_ts:%Y%m%d%H%M}.nc"
    r = knmi.SESSION.get(f"{knmi.KDP_URL}/datasets/{knmi.KDP_DATASET}/versions/{knmi.KDP_VERSION}/files",
                         params={"maxKeys": max_files, "startAfterFilename": after},
                         headers={"Authorization": knmi.kdp_key()}, timeout=30)
    if r.status_code == 429 or "Rate Limit" in r.text:
        raise RuntimeError("KDP rate limit exceeded")
    r.raise_for_status()
    files = [f["filename"] for f in r.json()["files"]]
    print(f"  10-min: {len(files)} new files after {last_ts:%Y-%m-%d %H:%M}Z" + (" (truncated, more next run)" if r.json()["isTruncated"] else ""))
    if not files:
        return pd.read_parquet(W_10MIN) if W_10MIN.exists() else pd.DataFrame()

    from concurrent.futures import ThreadPoolExecutor

    def one(fn):
        try:
            df = knmi.kdp_fetch_10min(fn)
            return df[df["station"].isin(stations)]
        except Exception as exc:  # noqa: BLE001
            print(f"  10-min: {fn} failed: {exc}", file=sys.stderr)
            return None

    # anonymous key is shared and slow-limited: stay serial there
    n_workers = workers if knmi.kdp_key() != knmi.KDP_ANONYMOUS_KEY else 1
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        frames = [f for f in pool.map(one, files) if f is not None]
    print(f"  10-min: {len(frames)}/{len(files)} files parsed")
    if not frames:
        return pd.read_parquet(W_10MIN) if W_10MIN.exists() else pd.DataFrame()
    return upsert_parquet(pd.concat(frames, ignore_index=True), W_10MIN, key=KEY)


def derive_daily(hourly: pd.DataFrame) -> pd.DataFrame:
    h = hourly.copy()
    h["date"] = pd.to_datetime(h["ts_utc"], utc=True).dt.tz_convert(LOCAL_TZ).dt.normalize().dt.tz_localize(None)
    g = h.groupby(["date", "station"])
    out = pd.DataFrame({
        "temp_mean_c": g["temp_c"].mean().round(2),
        "temp_min_c": g["temp_c"].min(),
        "temp_max_c": g["temp_c"].max(),
        "ghi_kwh_m2_day": (g["ghi_j_cm2"].sum() * 10_000 / 3.6e6).round(3),
        "sunshine_h": g["sunshine_h"].sum().round(1) if "sunshine_h" in h else pd.NA,
        "hours": g.size(),
    }).reset_index()
    return out[out["hours"] >= 20].drop(columns="hours")  # skip partial days


def make_chart(chart_days: int, station: int, path=CHART) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    BLUE, ORANGE = "#2a78d6", "#eb6834"
    SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"

    def local(df):
        df = df.copy()
        df["ts_local"] = pd.to_datetime(df["ts_utc"], utc=True).dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
        return df

    hourly = local(pd.read_parquet(W_HOURLY))
    hourly = hourly[hourly["station"] == station]
    tenmin = local(pd.read_parquet(W_10MIN)) if W_10MIN.exists() else pd.DataFrame()
    if not tenmin.empty:
        tenmin = tenmin[(tenmin["station"] == station) & (tenmin["ts_local"] > hourly["ts_local"].max())]
    daily = pd.read_parquet(W_DAILY)
    daily = daily[daily["station"] == station]
    name = hourly["stationname"].iloc[0] if "stationname" in hourly else f"station {station}"
    if not tenmin.empty and "stationname" in tenmin:
        name = tenmin["stationname"].iloc[0]

    end = max(hourly["ts_local"].max(), tenmin["ts_local"].max() if not tenmin.empty else hourly["ts_local"].max())
    t0 = end.normalize() - pd.Timedelta(days=chart_days - 1)
    h = hourly[hourly["ts_local"] >= t0]
    # hourly temp is observed at the END of the hour -> plot at ts+1h so it lines up with the 10-min series
    h_t = h["ts_local"] + pd.Timedelta(hours=1)

    plt.rcParams.update({"font.family": "sans-serif", "font.size": 9, "axes.edgecolor": AXIS, "axes.labelcolor": INK2,
                         "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})
    fig, axes = plt.subplots(3, 1, figsize=(13, 10), facecolor=SURFACE, gridspec_kw={"height_ratios": [1.2, 1.2, 1]})

    def style(ax, title, ylabel):
        ax.set_facecolor(SURFACE)
        ax.set_title(title, loc="left", fontsize=11, fontweight="bold", color=INK, pad=8)
        ax.set_ylabel(ylabel)
        ax.grid(True, axis="y", color=GRID, linewidth=0.8)
        ax.grid(False, axis="x")
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.tick_params(length=0)
        ax.set_axisbelow(True)
        ax.margins(x=0.01)

    ax = axes[0]
    ax.plot(h_t, h["temp_c"], color=BLUE, linewidth=1.6, label="hourly (validated)")
    if not tenmin.empty:
        ax.plot(tenmin["ts_local"], tenmin["temp_c"], color=BLUE, linewidth=1.2, alpha=0.55, label="10-min (near-real-time)")
        ax.legend(frameon=False, loc="upper left", fontsize=8)
        lt = tenmin.iloc[-1]
        ax.annotate(f"{lt['temp_c']:.1f} °C", (lt["ts_local"], lt["temp_c"]), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=8, color=INK2)
    style(ax, f"Outdoor temperature · {name} · last {chart_days} days", "°C")
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b"))

    ax = axes[1]
    ax.fill_between(h["ts_local"], 0, h["ghi_wm2"], step="post", color=ORANGE, alpha=0.25, linewidth=0)
    ax.step(h["ts_local"], h["ghi_wm2"], where="post", color=ORANGE, linewidth=1.2)
    if not tenmin.empty:
        ax.plot(tenmin["ts_local"], tenmin["ghi_wm2"], color=ORANGE, linewidth=1.0, alpha=0.6)
    style(ax, f"Global horizontal irradiance · {name} · hourly mean (10-min tail)", "W/m²")
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b"))
    ax.set_ylim(bottom=0)

    ax = axes[2]
    ax.bar(daily["date"], daily["ghi_kwh_m2_day"], width=1.0, color=ORANGE, alpha=0.8, linewidth=0)
    style(ax, f"Daily solar irradiation · {name}", "kWh/m²/day")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

    fig.text(0.01, 0.005, f"generated {dt.datetime.now():%Y-%m-%d %H:%M} · KNMI uurgegevens (validated, 1-2 day lag) + KDP 10-minute feed",
             fontsize=7, color=MUTED)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)
    print(f"chart -> {path}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--station", type=int, nargs="+", default=[260], help="KNMI station code(s); first one is charted")
    p.add_argument("--days-back", type=int, default=5)
    p.add_argument("--backfill-from", type=dt.date.fromisoformat)
    p.add_argument("--max-10min-files", type=int, default=300, help="cap per run (2 API calls each); 300 = 50 h")
    p.add_argument("--10min-since", dest="since", type=pd.Timestamp, help="force 10-min fetch start, e.g. 2026-09-13T01:00Z")
    p.add_argument("--chart-days", type=int, default=14)
    p.add_argument("--no-fetch", action="store_true")
    p.add_argument("--no-10min", action="store_true")
    p.add_argument("--no-chart", action="store_true")
    args = p.parse_args(argv)

    DATA_DIR.mkdir(exist_ok=True)
    today = dt.date.today()

    if not args.no_fetch:
        start = args.backfill_from or today - dt.timedelta(days=args.days_back)
        print(f"weather stations={args.station}  hourly {start} .. {today}")
        t0 = time.time()
        hourly = update_hourly(args.station, start, today)
        print(describe(hourly, "temp_c", "  hourly (total)"))
        daily = derive_daily(hourly)
        daily.to_parquet(W_DAILY, index=False)
        print(f"  daily: {len(daily)} station-days, last {daily['date'].max().date()}")
        if not args.no_10min:
            try:
                since = args.since.tz_localize("UTC") if args.since is not None and args.since.tzinfo is None else args.since
                tm = update_10min(args.station, args.max_10min_files, since)
                if not tm.empty:
                    print(describe(tm, "temp_c", "  10-min (total)"))
            except Exception as exc:  # noqa: BLE001
                print(f"  10-min skipped: {exc}", file=sys.stderr)
        print(f"fetched in {time.time() - t0:.1f}s")

    if not args.no_chart:
        if not W_HOURLY.exists():
            print("nothing to chart yet", file=sys.stderr)
            return 1
        make_chart(args.chart_days, args.station[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
