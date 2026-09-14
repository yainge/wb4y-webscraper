"""
Coverage / gap report for the central datasets in ./data.

    python check_datasets.py            # report
    python check_datasets.py --gaps     # also list the individual missing slots (first 20 per dataset)

Exit code 1 if any dataset has missing slots inside its own range or does not reach --expect-from (default 2025-01-01).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

import pandas as pd

from common import DATA_DIR, LOCAL_TZ

DATASETS = [
    # file, timestamp column, freq, group column (None = single series), value column
    ("electricity_prices_15min.parquet", "ts_utc", "15min", None, "price_eur_kwh"),
    ("electricity_prices_hourly.parquet", "ts_utc", "h", None, "price_eur_kwh"),
    ("gas_prices_hourly.parquet", "ts_utc", "h", None, "price_eur_m3"),
    ("gas_prices_daily.parquet", "gas_day", "D", None, "price_eur_m3"),
    ("weather_hourly.parquet", "ts_utc", "h", "station", "temp_c"),
    ("weather_daily.parquet", "date", "D", "station", "temp_mean_c"),
    ("weather_10min.parquet", "ts_utc", "10min", "station", "temp_c"),
]


def check(path, ts_col, freq, group, value_col, expect_from: dt.date, show_gaps: bool) -> bool:
    if not path.exists():
        print(f"{path.name:36s} MISSING FILE")
        return False
    df = pd.read_parquet(path)
    ts = pd.to_datetime(df[ts_col], utc=(ts_col == "ts_utc"))
    df = df.assign(_ts=ts)
    ok = True
    groups = [(None, df)] if group is None else list(df.groupby(group))
    for g, part in groups:
        t = part["_ts"].drop_duplicates().sort_values()
        expected = pd.date_range(t.min(), t.max(), freq=freq)
        missing = expected.difference(pd.DatetimeIndex(t))
        dups = int(part["_ts"].duplicated().sum())
        nan = int(part[value_col].isna().sum())
        first_local = t.min().tz_convert(LOCAL_TZ).date() if t.min().tzinfo else t.min().date()
        reaches = first_local <= expect_from
        src = f" sources={part['source'].value_counts().to_dict()}" if "source" in part else ""
        res = f" resolution={part['resolution'].value_counts().to_dict()}" if "resolution" in part else ""
        label = path.name if g is None else f"{path.name} [{group}={g}]"
        status = "OK " if (not len(missing) and not dups and reaches) else "!! "
        print(f"{status}{label:44s} {len(part):7d} rows  {t.min():%Y-%m-%d %H:%M} -> {t.max():%Y-%m-%d %H:%M}  "
              f"missing={len(missing)} dups={dups} nan={nan}{'' if reaches else f'  starts after {expect_from}'}{src}{res}")
        if show_gaps and len(missing):
            print("      first missing:", [str(x) for x in missing[:20]])
        ok &= status == "OK "
    return ok


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--expect-from", type=dt.date.fromisoformat, default=dt.date(2025, 1, 1))
    p.add_argument("--gaps", action="store_true")
    args = p.parse_args(argv)
    all_ok = True
    for name, ts_col, freq, group, value_col in DATASETS:
        # 10-min weather is a rolling near-real-time tail; it is not expected to reach back to 2025
        expect = args.expect_from if name != "weather_10min.parquet" else dt.date(2099, 1, 1)
        all_ok &= check(DATA_DIR / name, ts_col, freq, group, value_col, expect, args.gaps)
    print("\nALL OK" if all_ok else "\nPROBLEMS FOUND", file=sys.stdout if all_ok else sys.stderr)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
