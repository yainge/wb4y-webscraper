"""
Chart of the Tibber history in ./data (same style as Data Fetch APIs/market_prices_chart.png).

Panels (shared time axis, local time):
    1. daily energy at the meter: consumption (import) and production (feed-in), kWh/day
    2. daily money: consumption cost and feed-in profit, EUR/day
    3. hourly price: all-in `total` and market `energy` component, EUR/kWh (the gap is tax + VAT)
    4. last N days hourly: consumption vs feed-in, kWh/h (shows the solar/charging daily pattern)

Usage:
    python plot_tibber.py                 # -> data/tibber_chart.png
    python plot_tibber.py --recent-days 7 --out data/tibber_chart.png
"""

from __future__ import annotations

import argparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from common import DATA_DIR, LOCAL_TZ  # noqa: E402

# validated categorical palette (dataviz reference instance, light surface)
C_CONS, C_PROD, C_ENERGY, C_TOTAL = "#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"


def load(name: str) -> pd.DataFrame:
    df = pd.read_parquet(DATA_DIR / name)
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    df["ts_local"] = df["ts_utc"].dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
    return df.sort_values("ts_utc")


def daily(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    return df.set_index("ts_local")[cols].resample("D").sum(min_count=1)


def style(ax, ylabel: str, title: str):
    ax.set_title(title, loc="left", fontsize=11, color=INK, fontweight="bold", pad=8)
    ax.set_ylabel(ylabel, color=INK2, fontsize=9)
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.tick_params(colors=INK2, labelsize=8.5)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.margins(x=0.01)


def end_label(ax, x, y, text, color):
    ax.annotate(text, (x, y), xytext=(6, 0), textcoords="offset points", va="center", fontsize=8.5, color=INK, fontweight="bold")
    ax.plot([x], [y], "o", ms=5, color=color, mec=SURFACE, mew=1.5)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--recent-days", type=int, default=7)
    p.add_argument("--out", default=str(DATA_DIR / "tibber_chart.png"))
    args = p.parse_args(argv)

    cons = load("consumption_hourly.parquet")
    prod = load("production_hourly.parquet")
    price = load("prices_hourly.parquet")
    hourly = cons.merge(prod[["ts_utc", "production_kwh", "profit"]], on="ts_utc", how="outer").sort_values("ts_utc")
    hourly["ts_local"] = hourly["ts_utc"].dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
    d = daily(hourly, ["consumption_kwh", "production_kwh", "cost", "profit"])
    d = d[d[["consumption_kwh", "production_kwh"]].notna().any(axis=1)]
    complete = hourly.dropna(subset=["consumption_kwh"])["ts_local"].max()  # meter data lags ~1 day
    last_day = complete.normalize() - pd.Timedelta(days=1)  # last fully-known day
    d_full = d[d.index <= last_day]

    fig, axes = plt.subplots(4, 1, figsize=(14, 15), facecolor=SURFACE, gridspec_kw={"hspace": 0.55})
    home_id = str(cons["home_id"].iloc[0])[:8]
    start, end = hourly["ts_local"].min(), hourly["ts_local"].max()
    fig.suptitle(
        f"Tibber home {home_id}… — {start:%d %b %Y} to {end:%d %b %Y}  (GraphQL API, local time)",
        x=0.06, y=0.925, ha="left", fontsize=13, color=INK, fontweight="bold",
    )

    # 1 daily energy
    ax = axes[0]
    tot_c, tot_p = d_full["consumption_kwh"].sum(), d_full["production_kwh"].sum()
    ax.plot(d_full.index, d_full["consumption_kwh"], color=C_CONS, lw=2, label=f"consumption (import) — {tot_c:,.0f} kWh")
    ax.plot(d_full.index, d_full["production_kwh"], color=C_PROD, lw=2, label=f"production (feed-in) — {tot_p:,.0f} kWh")
    end_label(ax, d_full.index[-1], d_full["consumption_kwh"].iloc[-1], f"{d_full['consumption_kwh'].iloc[-1]:.1f}", C_CONS)
    end_label(ax, d_full.index[-1], d_full["production_kwh"].iloc[-1], f"{d_full['production_kwh'].iloc[-1]:.1f}", C_PROD)
    style(ax, "kWh / day", "Daily energy at the meter")
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, fontsize=9, loc="upper right", labelcolor=INK)

    # 2 daily money
    ax = axes[1]
    w = pd.Timedelta(hours=10)
    ax.bar(d_full.index - w / 2, d_full["cost"], width=w, color=C_CONS, label=f"cost of consumption — € {d_full['cost'].sum():,.2f}", linewidth=0)
    ax.bar(d_full.index + w / 2, d_full["profit"], width=w, color=C_PROD, label=f"feed-in profit — € {d_full['profit'].sum():,.2f}", linewidth=0)
    style(ax, "EUR / day", "Daily cost and feed-in profit")
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, fontsize=9, loc="upper right", labelcolor=INK)

    # 3 hourly prices
    ax = axes[2]
    ax.plot(price["ts_local"], price["total"], color=C_TOTAL, lw=0.9, label="total (all-in, incl. tax + VAT)")
    ax.plot(price["ts_local"], price["energy"], color=C_ENERGY, lw=0.9, label="energy (market price)")
    ax.fill_between(price["ts_local"], price["energy"], price["total"], color=C_TOTAL, alpha=0.08, linewidth=0)
    for col, colr in (("total", C_TOTAL), ("energy", C_ENERGY)):
        end_label(ax, price["ts_local"].iloc[-1], price[col].iloc[-1], f"{price[col].iloc[-1]:.3f}", colr)
    mean_t, mean_e = price["total"].mean(), price["energy"].mean()
    style(ax, "EUR / kWh", f"Hourly price — mean total {mean_t:.3f}, mean energy {mean_e:.3f} EUR/kWh")
    ax.set_ylim(min(0, price["energy"].min()) - 0.02, price["total"].max() * 1.3)  # headroom for the legend
    ax.legend(frameon=False, fontsize=9, loc="upper right", labelcolor=INK)

    # 4 recent hourly
    ax = axes[3]
    rec = hourly[hourly["ts_local"] >= end.normalize() - pd.Timedelta(days=args.recent_days)]
    ax.step(rec["ts_local"], rec["consumption_kwh"], where="post", color=C_CONS, lw=1.6, label="consumption")
    ax.step(rec["ts_local"], rec["production_kwh"], where="post", color=C_PROD, lw=1.6, label="feed-in")
    style(ax, "kWh / h", f"Last {args.recent_days} days, hourly (meter data lags ~1 day)")
    ax.set_ylim(bottom=0)
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b"))
    ax.legend(frameon=False, fontsize=9, loc="upper right", labelcolor=INK)

    for ax in axes[:3]:
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        ax.set_xlim(start.normalize(), end.normalize() + pd.Timedelta(days=1))

    fig.text(0.06, 0.005, f"source: Tibber GraphQL API · consumption/production per hour at the smart meter · prices = Tibber priceInfoRange · generated {pd.Timestamp.now():%Y-%m-%d %H:%M}",
             fontsize=8, color=INK2)
    fig.savefig(args.out, dpi=130, bbox_inches="tight", facecolor=SURFACE)
    print(f"saved {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
