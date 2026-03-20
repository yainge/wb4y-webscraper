from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import pandas as pd


@dataclass
class StorageFrames:
    contracts_fixed: pd.DataFrame
    contracts_variable: pd.DataFrame
    fixed_usage: pd.DataFrame
    variable_usage: pd.DataFrame
    fixed_fees: pd.DataFrame
    variable_fees: pd.DataFrame


def _read_parquet_if_exists(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame()


def load_storage_frames(storage_dir: str | Path) -> StorageFrames:
    root = Path(storage_dir).resolve()
    return StorageFrames(
        contracts_fixed=_read_parquet_if_exists(root / "contracts_fixed.parquet"),
        contracts_variable=_read_parquet_if_exists(root / "contracts_variable.parquet"),
        fixed_usage=_read_parquet_if_exists(root / "fixed_usage.parquet"),
        variable_usage=_read_parquet_if_exists(root / "variable_usage.parquet"),
        fixed_fees=_read_parquet_if_exists(root / "fixed_fees.parquet"),
        variable_fees=_read_parquet_if_exists(root / "variable_fees.parquet"),
    )


def combine_contracts(frames: StorageFrames) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    if not frames.contracts_fixed.empty:
        parts.append(frames.contracts_fixed.copy())
    if not frames.contracts_variable.empty:
        parts.append(frames.contracts_variable.copy())
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def combine_usage(frames: StorageFrames) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    if not frames.fixed_usage.empty:
        parts.append(frames.fixed_usage.copy())
    if not frames.variable_usage.empty:
        parts.append(frames.variable_usage.copy())
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def combine_fees(frames: StorageFrames) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    if not frames.fixed_fees.empty:
        parts.append(frames.fixed_fees.copy())
    if not frames.variable_fees.empty:
        parts.append(frames.variable_fees.copy())
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def _slugify(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_") or "unknown"


def build_contract_catalog(frames: StorageFrames) -> pd.DataFrame:
    catalog = combine_contracts(frames)
    if catalog.empty:
        return pd.DataFrame()

    catalog = catalog.copy()
    catalog["snapshot_month"] = catalog["snapshot_month"].astype("string")
    catalog["year"] = catalog["snapshot_month"].str.slice(0, 4).astype("Int64")
    catalog["estimated_annual_costs"] = pd.to_numeric(
        catalog["estimated_annual_costs"],
        errors="coerce",
    )
    catalog["duration_slug"] = catalog["contract_duration_label"].map(_slugify)
    catalog["offer_key"] = (
        catalog["provider_id"].astype("string")
        + "|"
        + catalog["contract_type"].astype("string")
        + "|"
        + catalog["contract_base_key"].astype("string")
        + "|"
        + catalog["duration_slug"].astype("string")
        + "|"
        + catalog["meter_type"].astype("string")
    )
    catalog["offer_label"] = (
        catalog["provider_name"].astype("string")
        + " | "
        + catalog["contract_base_name"].astype("string")
        + " | "
        + catalog["contract_duration_label"].astype("string")
        + " | "
        + catalog["meter_type"].astype("string")
    )
    return catalog
