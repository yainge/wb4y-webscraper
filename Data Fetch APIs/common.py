"""
Shared helpers for the market-price fetchers in this folder.

Conventions used by every script here:
  * timestamps are stored tz-aware in UTC in a column called ``ts_utc``
  * electricity prices are EUR/kWh (ex VAT), gas prices are EUR/m3 (ex VAT)
  * every row carries a ``source`` column so the origin can always be traced
  * parquet files are upserted, never blindly overwritten, so re-runs are safe
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pandas as pd

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv is in pyproject, but stay usable without it
    load_dotenv = None

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DATA_DIR = HERE / "data"

LOCAL_TZ = "Europe/Amsterdam"
NL_BIDDING_ZONE = "10YNL----------L"


def load_env() -> None:
    """Load a ``.env`` from the repo root (or this folder) into os.environ if present."""
    if load_dotenv is None:
        return
    for candidate in (REPO_ROOT / ".env", HERE / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)


def get_entsoe_token() -> str | None:
    load_env()
    return os.getenv("ENTSOE_TOKEN") or os.getenv("ENTSOE_SECURITY_TOKEN")


def local_day_bounds_utc(day: dt.date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the UTC start/end of a calendar day in the Netherlands (handles DST)."""
    start = pd.Timestamp(day).tz_localize(LOCAL_TZ)
    end = (pd.Timestamp(day) + pd.Timedelta(days=1)).tz_localize(LOCAL_TZ)
    return start.tz_convert("UTC"), end.tz_convert("UTC")


def daterange(start: dt.date, end: dt.date):
    cur = start
    while cur <= end:
        yield cur
        cur += dt.timedelta(days=1)


def upsert_parquet(
    new: pd.DataFrame,
    path: Path,
    key: str | list[str] = "ts_utc",
    priority: dict[str, int] | None = None,
) -> pd.DataFrame:
    """
    Merge ``new`` into the parquet at ``path`` keyed on ``key`` (a column name or a list of them).

    When two rows share a key the one with the *lowest* ``priority[source]`` wins;
    unknown sources get a large number. Without ``priority`` the newest row wins.
    Returns the combined frame that was written.
    """
    keys = [key] if isinstance(key, str) else list(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = [new]
    if path.exists():
        existing = pd.read_parquet(path)
        if "ts_utc" in keys:
            existing["ts_utc"] = pd.to_datetime(existing["ts_utc"], utc=True)
        frames.insert(0, existing)
    combined = pd.concat(frames, ignore_index=True)

    if priority and "source" in combined.columns:
        combined["_prio"] = combined["source"].map(priority).fillna(999).astype(int)
        # stable sort: for equal priority the later (newer) row wins
        combined["_order"] = range(len(combined))
        combined = combined.sort_values([*keys, "_prio", "_order"], ascending=[*(True for _ in keys), True, False])
        combined = combined.drop_duplicates(subset=keys, keep="first")
        combined = combined.drop(columns=["_prio", "_order"])
    else:
        combined = combined.drop_duplicates(subset=keys, keep="last")

    combined = combined.sort_values(keys).reset_index(drop=True)
    combined.to_parquet(path, index=False)
    return combined


def describe(df: pd.DataFrame, value_col: str, label: str = "") -> str:
    if df.empty:
        return f"{label}: <empty>"
    ts = pd.to_datetime(df["ts_utc"], utc=True)
    step = ts.drop_duplicates().sort_values().diff().dropna().mode()
    step_txt = str(step.iloc[0]) if len(step) else "n/a"
    return (
        f"{label}: {len(df)} rows | {ts.min()} -> {ts.max()} | step={step_txt} | "
        f"min={df[value_col].min():.5f} mean={df[value_col].mean():.5f} max={df[value_col].max():.5f}"
    )
