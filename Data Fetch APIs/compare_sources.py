"""
Cross-check the three sources for the same day(s):

    GridHub (Energiek) ELECTRICITY QUARTER   15-min   EUR/kWh
    GridHub (Energiek) ELECTRICITY HOUR      hourly   EUR/kWh
    Frank Energie      electricity           hourly   EUR/kWh
    ENTSO-E A44                              15-min   EUR/MWh -> EUR/kWh     (only when ENTSOE_TOKEN is set)
    Entsoe/entsoe_prices_2026.parquet        15-min   EUR/kWh               (offline reference already in repo)
    GridHub / Frank gas                      hourly   EUR/m3

Usage:
    python compare_sources.py                       # yesterday
    python compare_sources.py --start 2026-04-01 --end 2026-04-03
"""

from __future__ import annotations

import argparse
import datetime as dt

import pandas as pd

import test_frank_api as frank
import test_gridhub_api as gridhub
from common import REPO_ROOT, get_entsoe_token


def _series(df: pd.DataFrame, col: str) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    s = df.set_index(pd.DatetimeIndex(df["ts_utc"]))[col].sort_index()
    dups = s.index.duplicated().sum()
    if dups:
        print(f"  note: {dups} duplicate timestamps in '{col}' frame, keeping last")
        s = s[~s.index.duplicated(keep="last")]
    return s


def report(name_a: str, a: pd.Series, name_b: str, b: pd.Series) -> None:
    both = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner").dropna()
    if both.empty:
        print(f"  {name_a:<28} vs {name_b:<28}: no overlap")
        return
    d = (both["a"] - both["b"]).abs()
    print(f"  {name_a:<28} vs {name_b:<28}: n={len(both):4d}  max|diff|={d.max():.6f}  mean|diff|={d.mean():.6f}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=dt.date.fromisoformat)
    p.add_argument("--end", type=dt.date.fromisoformat)
    args = p.parse_args(argv)
    start = args.start or (dt.date.today() - dt.timedelta(days=1))
    end = args.end or start
    print(f"Comparing sources for {start} .. {end}\n")

    gh_q, _ = gridhub.fetch_range(gridhub.fetch_electricity, start, end, quarter=True)
    gh_h, _ = gridhub.fetch_range(gridhub.fetch_electricity, start, end, quarter=False)
    gh_gas, _ = gridhub.fetch_range(gridhub.fetch_gas, start, end)
    fr_e, fr_g, _ = frank.fetch_range(start, end)

    s_gh_q = _series(gh_q, "price_eur_kwh")
    s_gh_h = _series(gh_h, "price_eur_kwh")
    s_fr_e = _series(fr_e, "price_eur_kwh")
    s_gh_q_hourly = s_gh_q.resample("h").mean() if not s_gh_q.empty else s_gh_q

    print("Electricity")
    report("gridhub HOUR", s_gh_h, "frank hourly", s_fr_e)
    report("mean(gridhub QUARTER)", s_gh_q_hourly, "frank hourly", s_fr_e)
    report("mean(gridhub QUARTER)", s_gh_q_hourly, "gridhub HOUR", s_gh_h)

    ref_path = REPO_ROOT / "Entsoe" / "entsoe_prices_2026.parquet"
    if ref_path.exists():
        ref = pd.read_parquet(ref_path)
        ref["ts_utc"] = pd.to_datetime(ref["ts_utc"], utc=True)
        report("gridhub QUARTER", s_gh_q, "repo ENTSO-E parquet", _series(ref, "price"))

    token = get_entsoe_token()
    if token:
        import test_entsoe_api as entsoe

        try:
            en = entsoe.fetch_days(start, end, token)
            report("gridhub QUARTER", s_gh_q, "ENTSO-E API (live)", _series(en, "price_eur_kwh"))
            report("mean(ENTSO-E 15-min)", _series(en, "price_eur_kwh").resample("h").mean(), "frank hourly", s_fr_e)
        except RuntimeError as exc:
            print(f"  ENTSO-E live: {exc}")
    else:
        print("  (ENTSOE_TOKEN not set -> live ENTSO-E comparison skipped)")

    print("\nGas")
    report("gridhub gas hourly", _series(gh_gas, "price_eur_m3"), "frank gas hourly", _series(fr_g, "price_eur_m3"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
