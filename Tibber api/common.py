"""
Shared helpers for the Tibber Data API scripts in this folder.

Conventions (same as "Data Fetch APIs"):
  * timestamps are stored tz-aware in UTC in a column called ``ts_utc``; ``ts_local`` keeps the
    home's local time as delivered by the API (Europe/Amsterdam for a Dutch home)
  * every row carries ``source="tibber"`` plus ``home_id`` / ``device_id`` so the origin is traceable
  * parquet files are upserted on (device_id, ts_utc), never blindly overwritten, so re-runs are safe
"""

from __future__ import annotations

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
TOKEN_FILE = HERE / "tokens.json"  # gitignored

LOCAL_TZ = "Europe/Amsterdam"


def load_env() -> None:
    """Load a ``.env`` from the repo root (or this folder) into os.environ if present."""
    if load_dotenv is None:
        return
    for candidate in (REPO_ROOT / ".env", HERE / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)


def env(name: str, default: str | None = None) -> str | None:
    load_env()
    value = os.getenv(name)
    return value if value not in (None, "") else default


def upsert_parquet(new: pd.DataFrame, path: Path, key: str | list[str] = "ts_utc") -> pd.DataFrame:
    """Merge ``new`` into the parquet at ``path`` keyed on ``key``; the newest row wins. Returns the result."""
    keys = [key] if isinstance(key, str) else list(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = [new]
    if path.exists():
        existing = pd.read_parquet(path)
        if "ts_utc" in keys:
            existing["ts_utc"] = pd.to_datetime(existing["ts_utc"], utc=True)
        frames.insert(0, existing)
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=keys, keep="last")
    combined = combined.sort_values(keys).reset_index(drop=True)
    combined.to_parquet(path, index=False)
    return combined


def describe(df: pd.DataFrame, label: str = "") -> str:
    if df.empty:
        return f"{label}: <empty>"
    ts = pd.to_datetime(df["ts_utc"], utc=True)
    step = ts.drop_duplicates().sort_values().diff().dropna().mode()
    step_txt = str(step.iloc[0]) if len(step) else "n/a"
    value_cols = [c for c in df.columns if c not in {"ts_utc", "ts_local", "home_id", "device_id", "source", "resolution"}]
    return f"{label}: {len(df)} rows | {ts.min()} -> {ts.max()} | step={step_txt} | columns={value_cols}"
