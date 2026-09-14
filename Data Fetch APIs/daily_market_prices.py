"""
Daily market-price updater: electricity (15-min) + gas (hourly & daily) -> parquet -> chart.

Sources, in priority order (all agree to <1e-5 EUR, see compare_sources.py):
    electricity 15-min : ENTSO-E A44 (if ENTSOE_TOKEN set) -> GridHub/Energiek QUARTER -> Frank hourly (expanded to 15-min)
    gas hourly         : GridHub/Energiek GAS -> Frank gas
    gas daily          : derived from hourly (price of gas day D = value at 06:00 local on D)

Outputs (in ./data):
    electricity_prices_15min.parquet   ts_utc, price_eur_kwh, source, resolution
    electricity_prices_hourly.parquet  ts_utc, price_eur_kwh  (mean of the four quarter-hours)
    gas_prices_hourly.parquet          ts_utc, price_eur_m3, source
    gas_prices_daily.parquet           gas_day, price_eur_m3, calendar_day_mean_eur_m3, source
    market_prices_chart.png            3 panels: 15-min electricity (last N days), daily electricity, daily gas

Idempotent: every run re-fetches the last --days-back days plus tomorrow and upserts; a better source
(lower priority number) replaces rows from a worse one, so a Frank-filled gap is healed later by GridHub.

Usage:
    python daily_market_prices.py                          # last 3 days + tomorrow, then chart
    python daily_market_prices.py --backfill-from 2025-01-01   # one-off history load (bulk ENTSO-E, then fallbacks)
    python daily_market_prices.py --chart-days 30 --no-fetch   # only redraw the chart
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

import pandas as pd

import test_frank_api as frank
import test_gridhub_api as gridhub
from common import DATA_DIR, LOCAL_TZ, daterange, describe, get_entsoe_token, upsert_parquet

ELEC_15M = DATA_DIR / "electricity_prices_15min.parquet"
ELEC_1H = DATA_DIR / "electricity_prices_hourly.parquet"
GAS_1H = DATA_DIR / "gas_prices_hourly.parquet"
GAS_1D = DATA_DIR / "gas_prices_daily.parquet"
CHART = DATA_DIR / "market_prices_chart.png"

ELEC_PRIORITY = {"entsoe": 0, "gridhub": 1, "frank": 2}
GAS_PRIORITY = {"gridhub": 0, "frank": 1}


def _expected_slots(day: dt.date, minutes: int) -> int:
    s = pd.Timestamp(day).tz_localize(LOCAL_TZ)
    e = (pd.Timestamp(day) + pd.Timedelta(days=1)).tz_localize(LOCAL_TZ)
    return int((e - s) / pd.Timedelta(minutes=minutes))


def _expand_hourly_to_15min(df: pd.DataFrame, value_col: str, source: str = "frank") -> pd.DataFrame:
    """Repeat each hourly value on the four quarter-hours; resolution=PT60M flags that it is not a real 15-min price."""
    if df.empty:
        return pd.DataFrame(columns=["ts_utc", value_col, "source", "resolution"])
    parts = [df[["ts_utc", value_col]].assign(ts_utc=df["ts_utc"] + pd.Timedelta(minutes=15 * k)) for k in range(4)]
    out = pd.concat(parts, ignore_index=True).sort_values("ts_utc").reset_index(drop=True)
    out["source"] = source
    out["resolution"] = "PT60M"
    return out


def _entsoe_to_15min(df: pd.DataFrame) -> pd.DataFrame:
    """ENTSO-E rows -> 15-min grid. Before the SDAC 15-min go-live (2025-10-01) NL prices are PT60M."""
    cols = ["ts_utc", "price_eur_kwh", "source", "resolution"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    q = df[df["resolution"] == "PT15M"][cols]
    h = _expand_hourly_to_15min(df[df["resolution"] == "PT60M"], "price_eur_kwh", source="entsoe")
    return pd.concat([q, h], ignore_index=True).sort_values("ts_utc").reset_index(drop=True)


# --------------------------------------------------------------------------- electricity
def fetch_electricity_day(day: dt.date, token: str | None) -> pd.DataFrame:
    want = _expected_slots(day, 15)

    if token:
        import test_entsoe_api as entsoe

        try:
            df = _entsoe_to_15min(entsoe.fetch_days(day, day, token))
            if len(df) == want:
                return df
            print(f"  {day}: ENTSO-E returned {len(df)}/{want} slots, trying GridHub")
        except (RuntimeError, Exception) as exc:  # noqa: BLE001 - keep the daily job alive
            print(f"  {day}: ENTSO-E failed ({exc}), trying GridHub")

    try:
        df = gridhub.fetch_electricity(day, quarter=True)
        if len(df) == want:
            return df[["ts_utc", "price_eur_kwh", "source", "resolution"]]
        print(f"  {day}: GridHub returned {len(df)}/{want} quarter slots, trying Frank (hourly)")
    except Exception as exc:  # noqa: BLE001
        print(f"  {day}: GridHub failed ({exc}), trying Frank (hourly)")

    try:
        e, _ = frank.fetch_day(day)
        if not e.empty:
            return _expand_hourly_to_15min(e, "price_eur_kwh")
    except Exception as exc:  # noqa: BLE001
        print(f"  {day}: Frank failed ({exc})")
    return pd.DataFrame(columns=["ts_utc", "price_eur_kwh", "source", "resolution"])


def backfill_electricity_bulk(start: dt.date, end: dt.date, token: str, chunk_days: int = 90) -> pd.DataFrame:
    """One ENTSO-E request per <=90-day chunk (the API caps a response at 100 TimeSeries = 100 days)."""
    import test_entsoe_api as entsoe

    frames = []
    s = start
    while s <= end:
        e = min(s + dt.timedelta(days=chunk_days - 1), end)
        try:
            df = _entsoe_to_15min(entsoe.fetch_days(s, e, token))
            print(f"  ENTSO-E bulk {s}..{e}: {len(df)} slots")
            frames.append(df)
        except Exception as exc:  # noqa: BLE001
            print(f"  ENTSO-E bulk {s}..{e} failed: {exc}")
        s = e + dt.timedelta(days=1)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["ts_utc", "price_eur_kwh", "source", "resolution"])


def incomplete_days(df: pd.DataFrame, start: dt.date, end: dt.date) -> list[dt.date]:
    """Local calendar days in [start, end] that do not have every 15-min slot in df."""
    if df.empty:
        return list(daterange(start, end))
    have = pd.to_datetime(df["ts_utc"], utc=True).dt.tz_convert(LOCAL_TZ).dt.date.value_counts()
    return [d for d in daterange(start, end) if have.get(d, 0) < _expected_slots(d, 15)]


# --------------------------------------------------------------------------- gas
def fetch_gas_day(day: dt.date) -> pd.DataFrame:
    try:
        df = gridhub.fetch_gas(day)
        if not df.empty:
            return df[["ts_utc", "price_eur_m3", "source"]]
    except Exception as exc:  # noqa: BLE001
        print(f"  {day}: GridHub gas failed ({exc}), trying Frank")
    try:
        _, g = frank.fetch_day(day)
        if not g.empty:
            return g[["ts_utc", "price_eur_m3", "source"]]
    except Exception as exc:  # noqa: BLE001
        print(f"  {day}: Frank gas failed ({exc})")
    return pd.DataFrame(columns=["ts_utc", "price_eur_m3", "source"])


def derive_gas_daily(hourly: pd.DataFrame) -> pd.DataFrame:
    h = hourly.copy()
    h["ts_local"] = pd.to_datetime(h["ts_utc"], utc=True).dt.tz_convert(LOCAL_TZ)
    h["calendar_day"] = h["ts_local"].dt.date
    at_six = h[h["ts_local"].dt.hour == 6].set_index("calendar_day")
    cal_mean = h.groupby("calendar_day")["price_eur_m3"].mean().rename("calendar_day_mean_eur_m3")
    out = pd.DataFrame(
        {
            "gas_day": at_six.index,
            "price_eur_m3": at_six["price_eur_m3"].to_numpy(),
            "source": at_six["source"].to_numpy(),
        }
    ).set_index("gas_day")
    out = out.join(cal_mean, how="left").reset_index()
    out["gas_day"] = pd.to_datetime(out["gas_day"])
    return out.sort_values("gas_day").reset_index(drop=True)


# --------------------------------------------------------------------------- chart
def make_chart(chart_days: int, path=CHART) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    # reference palette (dataviz skill): slot-1 blue, slot-2 orange, chrome inks
    BLUE, ORANGE = "#2a78d6", "#eb6834"
    SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"

    elec = pd.read_parquet(ELEC_15M)
    elec["ts_local"] = pd.to_datetime(elec["ts_utc"], utc=True).dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
    gas = pd.read_parquet(GAS_1D)

    daily = (
        elec.set_index("ts_local")["price_eur_kwh"].resample("D").agg(["mean", "min", "max"]).dropna(subset=["mean"])
    )
    recent = elec[elec["ts_local"] >= elec["ts_local"].max().normalize() - pd.Timedelta(days=chart_days - 1)]

    plt.rcParams.update({"font.family": "sans-serif", "font.size": 9, "axes.edgecolor": AXIS, "axes.labelcolor": INK2,
                         "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})
    fig, axes = plt.subplots(3, 1, figsize=(13, 10), facecolor=SURFACE, gridspec_kw={"height_ratios": [1.3, 1, 1]})

    def style(ax, title, ylabel):
        ax.set_facecolor(SURFACE)
        ax.set_title(title, loc="left", fontsize=11, fontweight="bold", color=INK, pad=8)
        ax.set_ylabel(ylabel)
        ax.grid(True, axis="y", color=GRID, linewidth=0.8)
        ax.grid(False, axis="x")
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.tick_params(length=0)

    # 1) last N days, 15-min, step line (prices are block values)
    ax = axes[0]
    ax.step(recent["ts_local"], recent["price_eur_kwh"], where="post", color=BLUE, linewidth=1.2)
    ax.axhline(0, color=AXIS, linewidth=0.8)
    last = recent.iloc[-1]
    ax.annotate(f"{last['price_eur_kwh']:.3f}", (last["ts_local"], last["price_eur_kwh"]),
                xytext=(6, 0), textcoords="offset points", va="center", fontsize=8, color=INK2)
    style(ax, f"Electricity day-ahead, 15-minute · last {chart_days} days (NL, ex VAT)", "EUR/kWh")
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b"))
    ax.margins(x=0.01)

    # 2) full history, daily mean with min/max band
    ax = axes[1]
    ax.fill_between(daily.index, daily["min"], daily["max"], color=BLUE, alpha=0.15, linewidth=0)
    ax.plot(daily.index, daily["mean"], color=BLUE, linewidth=1.6)
    ax.axhline(0, color=AXIS, linewidth=0.8)
    ax.annotate(f"{daily['mean'].iloc[-1]:.3f}", (daily.index[-1], daily["mean"].iloc[-1]),
                xytext=(6, 0), textcoords="offset points", va="center", fontsize=8, color=INK2)
    style(ax, "Electricity day-ahead · daily mean (band = daily min–max)", "EUR/kWh")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.margins(x=0.01)

    # 3) gas daily
    ax = axes[2]
    ax.step(gas["gas_day"], gas["price_eur_m3"], where="post", color=ORANGE, linewidth=1.6)
    ax.annotate(f"{gas['price_eur_m3'].iloc[-1]:.3f}", (gas["gas_day"].iloc[-1], gas["price_eur_m3"].iloc[-1]),
                xytext=(6, 0), textcoords="offset points", va="center", fontsize=8, color=INK2)
    style(ax, "Gas day-ahead · daily (gas day 06:00–06:00, ex VAT)", "EUR/m³")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.margins(x=0.01)

    src = ", ".join(f"{k}: {v}" for k, v in elec["source"].value_counts().to_dict().items())
    fig.text(0.01, 0.005, f"generated {dt.datetime.now():%Y-%m-%d %H:%M} · electricity rows by source → {src}",
             fontsize=7, color=MUTED)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)
    print(f"chart -> {path}")


# --------------------------------------------------------------------------- main
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days-back", type=int, default=3, help="re-fetch this many past days (default 3)")
    p.add_argument("--backfill-from", type=dt.date.fromisoformat, help="fetch everything from this date")
    p.add_argument("--chart-days", type=int, default=14)
    p.add_argument("--no-fetch", action="store_true")
    p.add_argument("--no-chart", action="store_true")
    args = p.parse_args(argv)

    DATA_DIR.mkdir(exist_ok=True)
    today = dt.date.today()
    tomorrow = today + dt.timedelta(days=1)

    if not args.no_fetch:
        start = args.backfill_from or (today - dt.timedelta(days=args.days_back))
        token = get_entsoe_token()
        print(f"fetching {start} .. {tomorrow}  (ENTSO-E token: {'yes' if token else 'no'})")
        t0 = time.time()

        elec_frames, gas_frames = [], []
        elec_days = list(daterange(start, tomorrow))
        if token and (tomorrow - start).days > 7:
            # long range: bulk ENTSO-E first, then only the days that are still incomplete go through the per-day chain
            bulk = backfill_electricity_bulk(start, today, token)
            if not bulk.empty:
                elec_frames.append(bulk)
            elec_days = incomplete_days(bulk, start, tomorrow)
            print(f"  {len(elec_days)} day(s) still incomplete after bulk fetch -> per-day fallback chain")
        for day in elec_days:
            e = fetch_electricity_day(day, token)
            if not e.empty:
                elec_frames.append(e)
            elif day <= today:
                print(f"  {day}: NO electricity data from any source")
        for day in daterange(start, tomorrow):
            g = fetch_gas_day(day)
            if not g.empty:
                gas_frames.append(g)
        print(f"fetched in {time.time() - t0:.1f}s")

        if elec_frames:
            new_e = pd.concat(elec_frames, ignore_index=True)
            new_e["ts_utc"] = pd.to_datetime(new_e["ts_utc"], utc=True)
            all_e = upsert_parquet(new_e, ELEC_15M, priority=ELEC_PRIORITY)
            hourly = all_e.set_index("ts_utc")["price_eur_kwh"].resample("h").mean().dropna().reset_index()
            hourly.to_parquet(ELEC_1H, index=False)
            print(describe(all_e, "price_eur_kwh", "electricity 15-min (total)"))
            print(f"   sources: {all_e['source'].value_counts().to_dict()}")
        if gas_frames:
            new_g = pd.concat(gas_frames, ignore_index=True)
            new_g["ts_utc"] = pd.to_datetime(new_g["ts_utc"], utc=True)
            all_g = upsert_parquet(new_g, GAS_1H, priority=GAS_PRIORITY)
            daily = derive_gas_daily(all_g)
            daily.to_parquet(GAS_1D, index=False)
            print(describe(all_g, "price_eur_m3", "gas hourly (total)      "))
            print(f"   gas daily: {len(daily)} gas days, last = {daily['gas_day'].iloc[-1].date()} "
                  f"@ {daily['price_eur_m3'].iloc[-1]:.5f} EUR/m3")

    if not args.no_chart:
        if not (ELEC_15M.exists() and GAS_1D.exists()):
            print("nothing to chart yet", file=sys.stderr)
            return 1
        make_chart(args.chart_days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
