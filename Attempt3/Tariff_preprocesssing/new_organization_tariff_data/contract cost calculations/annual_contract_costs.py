from __future__ import annotations

import json
from pathlib import Path
import sys
from functools import lru_cache

import pandas as pd

from parquet_loader import (
    StorageFrames,
    build_contract_catalog,
    combine_fees,
    combine_usage,
    load_storage_frames,
)
from storage_paths import resolve_profile_path, resolve_storage_dir


FEEDIN_DIR = Path(__file__).resolve().parent.parent / "feedin tariffs"
if FEEDIN_DIR.exists() and str(FEEDIN_DIR) not in sys.path:
    sys.path.insert(0, str(FEEDIN_DIR))

try:
    from feed_in_lookup import get_feed_in_tariff
except ImportError:  # pragma: no cover - fallback when lookup helper is unavailable
    get_feed_in_tariff = None


TARIFF_BAND_MAP = {
    "normal": "peak",
    "peak": "peak",
    "off-peak": "offpeak",
    "offpeak": "offpeak",
}

VECTOR_COLS = ["electricity_peak", "electricity_offpeak", "gas"]
RATE_OUTPUT_COLS = {
    "electricity_peak": "electricity_peak_rate_eur_per_kwh",
    "electricity_offpeak": "electricity_offpeak_rate_eur_per_kwh",
    "gas": "gas_rate_eur_per_m3",
}
USAGE_OUTPUT_COLS = {
    "electricity_peak": "annual_peak_import_kwh",
    "electricity_offpeak": "annual_offpeak_import_kwh",
    "gas": "annual_gas_m3",
}


def load_meter_profile(profile_path: str | Path) -> pd.DataFrame:
    profile_file = Path(profile_path).resolve()
    with profile_file.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    meter_data = pd.json_normalize(raw)
    meter_data["timestamp"] = pd.to_datetime(meter_data["timestamp"], utc=True, errors="coerce")
    for column in ["import_kwh", "feedin_kwh", "net_load_kwh"]:
        meter_data[column] = pd.to_numeric(meter_data[column], errors="coerce").fillna(0.0)
    meter_data["snapshot_month"] = meter_data["timestamp"].dt.strftime("%Y-%m")
    meter_data["tariff_band"] = (
        meter_data["tariff_period"].astype("string").str.lower().map(TARIFF_BAND_MAP).fillna("single")
    )
    return meter_data


def build_consumption_inputs(
    meter_data: pd.DataFrame,
    annual_gas_m3: float = 800.0,
) -> dict[str, object]:
    monthly_peak = (
        meter_data[meter_data["tariff_band"] == "peak"]
        .groupby("snapshot_month", dropna=False)["import_kwh"]
        .sum()
    )
    monthly_offpeak = (
        meter_data[meter_data["tariff_band"] == "offpeak"]
        .groupby("snapshot_month", dropna=False)["import_kwh"]
        .sum()
    )
    month_day_weights = (
        meter_data.assign(day_count=meter_data["timestamp"].dt.days_in_month)
        .groupby("snapshot_month", dropna=False)["day_count"]
        .max()
        .astype(float)
        .sort_index()
    )

    monthly_usage_matrix = (
        pd.DataFrame(
            {
                "electricity_peak": monthly_peak,
                "electricity_offpeak": monthly_offpeak,
            }
        )
        .fillna(0.0)
        .sort_index()
    )
    total_days = float(month_day_weights.sum())
    gas_weights = month_day_weights / total_days if total_days else month_day_weights * 0.0
    monthly_usage_matrix["gas"] = gas_weights.reindex(monthly_usage_matrix.index).fillna(0.0) * float(annual_gas_m3)

    annual_usage_vector = pd.DataFrame(
        [monthly_usage_matrix[VECTOR_COLS].sum()],
        index=pd.Index(["annual"], name="period"),
    )

    annual_import_kwh = float(meter_data["import_kwh"].sum())
    annual_feedin_kwh = float(meter_data["feedin_kwh"].sum())
    annual_net_load_kwh = float(meter_data["net_load_kwh"].sum())
    summary = pd.DataFrame(
        [
            {
                "annual_import_kwh": annual_import_kwh,
                "annual_feedin_kwh": annual_feedin_kwh,
                "annual_net_load_kwh": annual_net_load_kwh,
                "annual_gas_m3": float(annual_gas_m3),
                "annual_peak_import_kwh": float(annual_usage_vector.iloc[0]["electricity_peak"]),
                "annual_offpeak_import_kwh": float(annual_usage_vector.iloc[0]["electricity_offpeak"]),
            }
        ]
    )

    return {
        "summary": summary,
        "monthly_usage_matrix": monthly_usage_matrix[VECTOR_COLS],
        "annual_usage_vector": annual_usage_vector[VECTOR_COLS],
        "month_day_weights": month_day_weights.to_dict(),
        "annual_feedin_kwh": annual_feedin_kwh,
    }


def _prepare_catalog_usage_fees(
    frames: StorageFrames,
    contract_type: str,
    year: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    catalog = build_contract_catalog(frames)
    usage = combine_usage(frames)
    fees = combine_fees(frames)

    if catalog.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    catalog = catalog[catalog["contract_type"] == contract_type].copy()
    if year is not None:
        year_str = str(year)
        catalog = catalog[catalog["snapshot_month"].astype("string").str.slice(0, 4) == year_str]
        usage = usage[usage["snapshot_month"].astype("string").str.slice(0, 4) == year_str].copy()
        fees = fees[fees["snapshot_month"].astype("string").str.slice(0, 4) == year_str].copy()

    usage = usage.merge(
        catalog[
            [
                "contract_snapshot_key",
                "offer_key",
                "provider_id",
                "provider_name",
                "contract_base_key",
                "contract_base_name",
                "contract_duration_label",
                "meter_type",
                "snapshot_month",
                "estimated_annual_costs",
            ]
        ],
        on="contract_snapshot_key",
        how="inner",
        suffixes=("", "_contract"),
    )
    fees = fees.merge(
        catalog[
            [
                "contract_snapshot_key",
                "offer_key",
                "provider_id",
                "provider_name",
                "contract_base_key",
                "contract_base_name",
                "contract_duration_label",
                "meter_type",
                "snapshot_month",
                "estimated_annual_costs",
            ]
        ],
        on="contract_snapshot_key",
        how="inner",
        suffixes=("", "_contract"),
    )
    return catalog, usage, fees


def _rate_component(commodity: str, tariff_band: str) -> str | None:
    if commodity == "electricity" and tariff_band == "peak":
        return "electricity_peak"
    if commodity == "electricity" and tariff_band == "offpeak":
        return "electricity_offpeak"
    if commodity == "electricity" and tariff_band == "single":
        return "electricity_single"
    if commodity == "gas" and tariff_band == "single":
        return "gas"
    return None


def _build_rate_matrix(usage_rows: pd.DataFrame, index_cols: list[str]) -> pd.DataFrame:
    if usage_rows.empty:
        return pd.DataFrame(columns=VECTOR_COLS)

    rows = usage_rows[
        (usage_rows["direction"] == "import")
        & usage_rows["commodity"].isin(["electricity", "gas"])
    ].copy()
    rows["rate_component"] = rows.apply(
        lambda row: _rate_component(str(row["commodity"]), str(row["tariff_band"])),
        axis=1,
    )
    rows = rows[rows["rate_component"].notna()].copy()
    rows["rate"] = pd.to_numeric(rows["rate"], errors="coerce")
    rows = rows.dropna(subset=["rate"])

    matrix = rows.pivot_table(
        index=index_cols,
        columns="rate_component",
        values="rate",
        aggfunc="first",
    )
    matrix.columns.name = None

    if "electricity_single" in matrix.columns:
        single_rate = matrix["electricity_single"]
        if "electricity_peak" not in matrix.columns:
            matrix["electricity_peak"] = single_rate
        else:
            matrix["electricity_peak"] = matrix["electricity_peak"].fillna(single_rate)
        if "electricity_offpeak" not in matrix.columns:
            matrix["electricity_offpeak"] = single_rate
        else:
            matrix["electricity_offpeak"] = matrix["electricity_offpeak"].fillna(single_rate)
        matrix = matrix.drop(columns=["electricity_single"])

    if "electricity_peak" not in matrix.columns:
        matrix["electricity_peak"] = 0.0
    if "electricity_offpeak" not in matrix.columns:
        matrix["electricity_offpeak"] = 0.0
    if "gas" not in matrix.columns:
        matrix["gas"] = 0.0

    matrix["electricity_peak"] = matrix["electricity_peak"].fillna(matrix["electricity_offpeak"]).fillna(0.0)
    matrix["electricity_offpeak"] = matrix["electricity_offpeak"].fillna(matrix["electricity_peak"]).fillna(0.0)
    matrix["gas"] = matrix["gas"].fillna(0.0)
    return matrix[VECTOR_COLS].sort_index()


def _build_fee_total_series(fee_rows: pd.DataFrame, index_cols: list[str]) -> pd.Series:
    if fee_rows.empty:
        return pd.Series(dtype="float64", name="fixed_fee_cost_eur")

    normalized = fee_rows.copy()
    normalized["annual_fee_eur"] = pd.to_numeric(
        normalized["annual_amount"],
        errors="coerce",
    ).fillna(pd.to_numeric(normalized["amount"], errors="coerce"))
    grouped = normalized.groupby(index_cols, dropna=False)["annual_fee_eur"].sum()
    grouped.name = "fixed_fee_cost_eur"
    return grouped.sort_index()


@lru_cache(maxsize=1)
def _load_feed_in_reference() -> dict[str, object]:
    feed_in_path = FEEDIN_DIR / "feed_in_tariffs.json"
    if not feed_in_path.exists():
        return {}
    with feed_in_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_provider_token(value: str) -> str:
    lowered = str(value or "").strip().lower()
    chars = [char if char.isalnum() else " " for char in lowered]
    return " ".join("".join(chars).split())


def _match_dynamic_provider(provider_id: str, provider_name: str) -> tuple[str | None, dict[str, object] | None]:
    reference = _load_feed_in_reference().get("dynamic_contracts", {})
    provider_keys = {_normalize_provider_token(provider_id), _normalize_provider_token(provider_name)}
    for category_name, category_data in reference.items():
        for provider in category_data.get("providers", []):
            candidate = _normalize_provider_token(provider.get("name", ""))
            if candidate and candidate in provider_keys:
                return category_name, provider
    return None, None


def _estimate_dynamic_feed_in_cost(
    provider_id: str,
    provider_name: str,
    annual_import_kwh: float,
    annual_feedin_kwh: float,
) -> float | None:
    category_name, provider = _match_dynamic_provider(provider_id, provider_name)
    if not category_name or provider is None:
        return None

    if category_name == "standard_receive_compensation":
        return -float(provider.get("compensation_per_kwh_eur", 0.0)) * annual_feedin_kwh
    if category_name == "pay_procurement_charge":
        return float(provider.get("procurement_charge_per_kwh_eur", 0.0)) * annual_feedin_kwh
    if category_name == "pay_on_surplus_only":
        surplus_kwh = max(0.0, annual_feedin_kwh - annual_import_kwh)
        return float(provider.get("surplus_charge_per_kwh_eur", 0.0)) * surplus_kwh
    if category_name == "no_compensation_no_charge":
        return 0.0
    return None


@lru_cache(maxsize=128)
def _benchmark_feed_in_cost(
    contract_duration_label: str,
    annual_feedin_kwh: float,
) -> float:
    if get_feed_in_tariff is None or annual_feedin_kwh <= 0:
        return 0.0

    reference = _load_feed_in_reference().get("fixed_and_variable_contracts", {})
    estimates: list[float] = []
    for provider_key in reference.keys():
        tariff = get_feed_in_tariff(provider_key, contract_duration_label, annual_feedin_kwh)
        if tariff is not None:
            estimates.append(float(tariff))
    if estimates:
        return float(sum(estimates) / len(estimates))
    return 0.0


def _estimate_feed_in_cost(
    provider_id: str,
    provider_name: str,
    contract_duration_label: str,
    annual_import_kwh: float,
    annual_feedin_kwh: float,
) -> float:
    if get_feed_in_tariff is None or annual_feedin_kwh <= 0:
        return 0.0

    for provider_value in [provider_id, provider_name]:
        if not provider_value:
            continue
        tariff = get_feed_in_tariff(
            provider_value,
            contract_duration_label,
            annual_feedin_kwh,
        )
        if tariff is not None:
            return float(tariff)

    dynamic_tariff = _estimate_dynamic_feed_in_cost(
        provider_id,
        provider_name,
        annual_import_kwh,
        annual_feedin_kwh,
    )
    if dynamic_tariff is not None:
        return float(dynamic_tariff)

    return _benchmark_feed_in_cost(contract_duration_label, annual_feedin_kwh)


def _append_feed_in_costs(
    annual_offer_costs: pd.DataFrame,
    annual_import_kwh: float,
    annual_feedin_kwh: float,
) -> pd.DataFrame:
    if annual_offer_costs.empty:
        return annual_offer_costs

    enriched = annual_offer_costs.copy()
    enriched["feed_in_cost_eur"] = enriched.apply(
        lambda row: _estimate_feed_in_cost(
            str(row.get("provider_id", "")),
            str(row.get("provider_name", "")),
            str(row.get("contract_duration_label", "")),
            annual_import_kwh,
            annual_feedin_kwh,
        ),
        axis=1,
    )
    enriched["total_annual_cost_eur"] = enriched["total_annual_cost_eur"] + enriched["feed_in_cost_eur"]
    return enriched


def build_fixed_tariff_matrix(
    frames: StorageFrames,
    year: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    catalog, usage, fees = _prepare_catalog_usage_fees(frames, contract_type="fixed", year=year)
    if catalog.empty:
        return pd.DataFrame(), pd.DataFrame()

    selected = (
        catalog.sort_values(["offer_key", "snapshot_month", "contract_snapshot_key"])
        .drop_duplicates(subset=["offer_key"], keep="first")
        .copy()
        .set_index("offer_key")
    )
    selected_usage = usage[usage["contract_snapshot_key"].isin(selected["contract_snapshot_key"])]
    selected_fees = fees[fees["contract_snapshot_key"].isin(selected["contract_snapshot_key"])]

    rate_matrix = _build_rate_matrix(selected_usage, ["offer_key"])
    fee_series = _build_fee_total_series(selected_fees, ["offer_key"])

    metadata = selected[
        [
            "contract_snapshot_key",
            "contract_base_key",
            "provider_id",
            "provider_name",
            "contract_type",
            "contract_base_name",
            "contract_duration_label",
            "meter_type",
            "snapshot_month",
            "estimated_annual_costs",
        ]
    ].rename(
        columns={
            "snapshot_month": "pricing_reference_month",
            "estimated_annual_costs": "estimated_annual_costs_source",
        }
    )
    matrix = metadata.join(rate_matrix, how="left").join(fee_series, how="left")
    matrix[VECTOR_COLS] = matrix[VECTOR_COLS].fillna(0.0)
    matrix["fixed_fee_cost_eur"] = matrix["fixed_fee_cost_eur"].fillna(0.0)
    matrix["pricing_strategy"] = "fixed_first_available_month"
    return matrix.sort_index(), metadata


def build_variable_monthly_tariff_matrix(
    frames: StorageFrames,
    year: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    catalog, usage, fees = _prepare_catalog_usage_fees(frames, contract_type="variable", year=year)
    if catalog.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.Series(dtype="float64")

    rate_matrix = _build_rate_matrix(usage, ["offer_key", "snapshot_month"])
    metadata = (
        catalog.sort_values(["offer_key", "snapshot_month", "contract_snapshot_key"])
        .drop_duplicates(subset=["offer_key"], keep="first")
        .set_index("offer_key")[
            [
                "contract_base_key",
                "provider_id",
                "provider_name",
                "contract_type",
                "contract_base_name",
                "contract_duration_label",
                "meter_type",
            ]
        ]
    )
    fee_series = _build_fee_total_series(fees, ["offer_key", "snapshot_month"])
    return rate_matrix.sort_index(), metadata.sort_index(), fee_series.sort_index()


def build_fixed_usage_matrix(
    fixed_tariff_matrix: pd.DataFrame,
    annual_usage_vector: pd.DataFrame,
) -> pd.DataFrame:
    if fixed_tariff_matrix.empty:
        return pd.DataFrame(columns=VECTOR_COLS)

    usage_row = annual_usage_vector[VECTOR_COLS].iloc[0]
    usage_matrix = pd.DataFrame(
        [usage_row.to_dict()] * len(fixed_tariff_matrix),
        index=fixed_tariff_matrix.index,
    )
    return usage_matrix[VECTOR_COLS]


def build_variable_monthly_usage_matrix(
    variable_monthly_tariff_matrix: pd.DataFrame,
    monthly_usage_matrix: pd.DataFrame,
) -> pd.DataFrame:
    if variable_monthly_tariff_matrix.empty:
        return pd.DataFrame(columns=VECTOR_COLS)

    usage = variable_monthly_tariff_matrix.reset_index()[["offer_key", "snapshot_month"]].merge(
        monthly_usage_matrix.reset_index(),
        on="snapshot_month",
        how="left",
    )
    usage = usage.set_index(["offer_key", "snapshot_month"]).sort_index()
    return usage[VECTOR_COLS].fillna(0.0)


def build_variable_annual_usage_matrix(
    variable_monthly_tariff_matrix: pd.DataFrame,
    annual_usage_vector: pd.DataFrame,
) -> pd.DataFrame:
    if variable_monthly_tariff_matrix.empty:
        return pd.DataFrame(columns=VECTOR_COLS)

    usage_row = annual_usage_vector[VECTOR_COLS].iloc[0]
    offer_index = pd.Index(
        variable_monthly_tariff_matrix.index.get_level_values("offer_key").unique(),
        name="offer_key",
    )
    usage_matrix = pd.DataFrame(
        [usage_row.to_dict()] * len(offer_index),
        index=offer_index,
    )
    return usage_matrix[VECTOR_COLS]


def calculate_fixed_annual_offer_costs(
    frames: StorageFrames,
    consumption: dict[str, object],
    year: int | None = None,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    fixed_tariff_matrix, _ = build_fixed_tariff_matrix(frames, year=year)
    if fixed_tariff_matrix.empty:
        return pd.DataFrame(), {
            "fixed_tariff_matrix": pd.DataFrame(),
            "fixed_usage_matrix": pd.DataFrame(),
            "fixed_cost_matrix": pd.DataFrame(),
        }

    fixed_usage_matrix = build_fixed_usage_matrix(
        fixed_tariff_matrix,
        consumption["annual_usage_vector"],
    )
    fixed_cost_matrix = fixed_tariff_matrix[VECTOR_COLS].mul(fixed_usage_matrix[VECTOR_COLS], axis=0)
    fixed_cost_matrix = fixed_cost_matrix.rename(
        columns={
            "electricity_peak": "electricity_peak_cost_eur",
            "electricity_offpeak": "electricity_offpeak_cost_eur",
            "gas": "gas_cost_eur",
        }
    )
    annual_offer_costs = fixed_tariff_matrix.copy()
    annual_offer_costs["electricity_cost_eur"] = (
        fixed_cost_matrix["electricity_peak_cost_eur"] + fixed_cost_matrix["electricity_offpeak_cost_eur"]
    )
    annual_offer_costs["gas_cost_eur"] = fixed_cost_matrix["gas_cost_eur"]
    annual_offer_costs["fixed_fee_cost_eur"] = annual_offer_costs["fixed_fee_cost_eur"].fillna(0.0)
    annual_offer_costs["total_annual_cost_eur"] = (
        annual_offer_costs["electricity_cost_eur"]
        + annual_offer_costs["gas_cost_eur"]
        + annual_offer_costs["fixed_fee_cost_eur"]
    )
    annual_offer_costs["months_available"] = 1

    annual_offer_costs = annual_offer_costs.rename(columns=RATE_OUTPUT_COLS)
    for usage_col, output_col in USAGE_OUTPUT_COLS.items():
        annual_offer_costs[output_col] = fixed_usage_matrix[usage_col]
    annual_offer_costs = _append_feed_in_costs(
        annual_offer_costs,
        float(consumption["summary"].iloc[0]["annual_import_kwh"]),
        float(consumption.get("annual_feedin_kwh", 0.0)),
    )

    annual_offer_costs = annual_offer_costs.reset_index().sort_values(
        ["total_annual_cost_eur", "provider_name", "contract_base_name", "meter_type"]
    ).reset_index(drop=True)
    return annual_offer_costs, {
        "fixed_tariff_matrix": fixed_tariff_matrix.reset_index(),
        "fixed_usage_matrix": fixed_usage_matrix.reset_index(),
        "fixed_cost_matrix": fixed_cost_matrix.reset_index(),
    }


def calculate_variable_annual_offer_costs(
    frames: StorageFrames,
    consumption: dict[str, object],
    year: int | None = None,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    contract_catalog = build_contract_catalog(frames)
    if year is not None and not contract_catalog.empty:
        contract_catalog = contract_catalog[
            contract_catalog["snapshot_month"].astype("string").str.slice(0, 4) == str(year)
        ].copy()
    variable_catalog = contract_catalog[contract_catalog["contract_type"] == "variable"].copy()
    if not variable_catalog.empty:
        variable_catalog["estimated_annual_costs"] = pd.to_numeric(
            variable_catalog["estimated_annual_costs"],
            errors="coerce",
        )

    variable_monthly_tariff_matrix, metadata, variable_monthly_fee_series = build_variable_monthly_tariff_matrix(
        frames,
        year=year,
    )
    if variable_monthly_tariff_matrix.empty:
        empty = pd.DataFrame()
        return empty, {
            "variable_monthly_tariff_matrix": empty,
            "variable_monthly_usage_matrix": empty,
            "variable_weighted_tariff_matrix": empty,
            "variable_annual_usage_matrix": empty,
            "variable_annual_cost_matrix": empty,
        }

    variable_monthly_usage_matrix = build_variable_monthly_usage_matrix(
        variable_monthly_tariff_matrix,
        consumption["monthly_usage_matrix"],
    )
    variable_annual_usage_matrix = build_variable_annual_usage_matrix(
        variable_monthly_tariff_matrix,
        consumption["annual_usage_vector"],
    )

    weighted_cost_numerators = variable_monthly_tariff_matrix[VECTOR_COLS].mul(
        variable_monthly_usage_matrix[VECTOR_COLS]
    )
    weighted_rate_denominators = variable_monthly_usage_matrix[VECTOR_COLS].groupby(level="offer_key").sum()
    variable_weighted_tariff_matrix = (
        weighted_cost_numerators.groupby(level="offer_key").sum().div(
            weighted_rate_denominators.where(weighted_rate_denominators != 0.0)
        )
    ).fillna(0.0)
    variable_weighted_tariff_matrix = variable_weighted_tariff_matrix.reindex(metadata.index).fillna(0.0)

    variable_annual_cost_matrix = variable_weighted_tariff_matrix[VECTOR_COLS].mul(
        variable_annual_usage_matrix[VECTOR_COLS],
        axis=0,
    )
    variable_annual_cost_matrix = variable_annual_cost_matrix.rename(
        columns={
            "electricity_peak": "electricity_peak_cost_eur",
            "electricity_offpeak": "electricity_offpeak_cost_eur",
            "gas": "gas_cost_eur",
        }
    )

    fee_df = variable_monthly_fee_series.rename("fixed_fee_cost_eur").reset_index()
    fee_df["month_weight"] = fee_df["snapshot_month"].map(consumption["month_day_weights"]).fillna(0.0)
    fee_df["weighted_fee"] = fee_df["fixed_fee_cost_eur"] * fee_df["month_weight"]
    weighted_fee = (
        fee_df.groupby("offer_key", dropna=False)["weighted_fee"].sum().div(
            fee_df.groupby("offer_key", dropna=False)["month_weight"].sum().where(
                fee_df.groupby("offer_key", dropna=False)["month_weight"].sum() != 0.0
            )
        )
    ).fillna(0.0)

    annual_offer_costs = metadata.join(variable_weighted_tariff_matrix, how="left")
    annual_usage_named = variable_annual_usage_matrix.rename(
        columns={column: f"{column}_usage" for column in VECTOR_COLS}
    )
    annual_offer_costs = annual_offer_costs.join(annual_usage_named, how="left")
    annual_offer_costs = annual_offer_costs.join(variable_annual_cost_matrix, how="left")
    annual_offer_costs = annual_offer_costs.join(weighted_fee.rename("fixed_fee_cost_eur"), how="left")
    annual_offer_costs["months_available"] = (
        variable_monthly_tariff_matrix.reset_index().groupby("offer_key")["snapshot_month"].nunique()
    )
    annual_offer_costs["available_months"] = (
        variable_monthly_tariff_matrix.reset_index().groupby("offer_key")["snapshot_month"].agg(list)
    )
    annual_offer_costs["pricing_strategy"] = "variable_weighted_average_2025"
    annual_offer_costs["estimated_annual_costs_source_mean"] = (
        variable_catalog
        .groupby("offer_key")["estimated_annual_costs"]
        .mean()
        .reindex(metadata.index)
    )

    annual_offer_costs["electricity_cost_eur"] = (
        annual_offer_costs["electricity_peak_cost_eur"].fillna(0.0)
        + annual_offer_costs["electricity_offpeak_cost_eur"].fillna(0.0)
    )
    annual_offer_costs["gas_cost_eur"] = annual_offer_costs["gas_cost_eur"].fillna(0.0)
    annual_offer_costs["fixed_fee_cost_eur"] = annual_offer_costs["fixed_fee_cost_eur"].fillna(0.0)
    annual_offer_costs["total_annual_cost_eur"] = (
        annual_offer_costs["electricity_cost_eur"]
        + annual_offer_costs["gas_cost_eur"]
        + annual_offer_costs["fixed_fee_cost_eur"]
    )

    annual_offer_costs = annual_offer_costs.rename(columns=RATE_OUTPUT_COLS)
    for usage_col, output_col in USAGE_OUTPUT_COLS.items():
        annual_offer_costs[output_col] = annual_offer_costs[f"{usage_col}_usage"]
    annual_offer_costs = _append_feed_in_costs(
        annual_offer_costs,
        float(consumption["summary"].iloc[0]["annual_import_kwh"]),
        float(consumption.get("annual_feedin_kwh", 0.0)),
    )

    annual_offer_costs = annual_offer_costs.reset_index().sort_values(
        ["total_annual_cost_eur", "provider_name", "contract_base_name", "meter_type"]
    ).reset_index(drop=True)
    return annual_offer_costs, {
        "variable_monthly_tariff_matrix": variable_monthly_tariff_matrix.reset_index(),
        "variable_monthly_usage_matrix": variable_monthly_usage_matrix.reset_index(),
        "variable_weighted_tariff_matrix": variable_weighted_tariff_matrix.reset_index(),
        "variable_annual_usage_matrix": variable_annual_usage_matrix.reset_index(),
        "variable_annual_cost_matrix": variable_annual_cost_matrix.reset_index(),
    }


def summarize_annual_offer_costs(annual_offer_costs: pd.DataFrame) -> pd.DataFrame:
    if annual_offer_costs.empty:
        return pd.DataFrame()

    summary = annual_offer_costs.groupby("contract_type", dropna=False).agg(
        offers=("offer_key", "count"),
        providers=("provider_name", "nunique"),
        avg_total_annual_cost_eur=("total_annual_cost_eur", "mean"),
        min_total_annual_cost_eur=("total_annual_cost_eur", "min"),
        max_total_annual_cost_eur=("total_annual_cost_eur", "max"),
    )
    return summary.reset_index()


def calculate_annual_contract_costs(
    storage_dir: str | Path | None = None,
    profile_path: str | Path | None = None,
    annual_gas_m3: float = 800.0,
    year: int | None = 2025,
) -> dict[str, object]:
    resolved_storage_dir = resolve_storage_dir(storage_dir)
    resolved_profile_path = resolve_profile_path(profile_path)
    frames = load_storage_frames(resolved_storage_dir)
    meter_data = load_meter_profile(resolved_profile_path)
    if year is not None:
        meter_data = meter_data[meter_data["snapshot_month"].astype("string").str.slice(0, 4) == str(year)].copy()

    consumption = build_consumption_inputs(meter_data, annual_gas_m3=annual_gas_m3)
    fixed_annual_offer_costs, fixed_matrices = calculate_fixed_annual_offer_costs(
        frames,
        consumption,
        year=year,
    )
    variable_annual_offer_costs, variable_matrices = calculate_variable_annual_offer_costs(
        frames,
        consumption,
        year=year,
    )
    annual_offer_costs = pd.concat(
        [fixed_annual_offer_costs, variable_annual_offer_costs],
        ignore_index=True,
        sort=False,
    ).sort_values(
        ["contract_type", "total_annual_cost_eur", "provider_name"]
    ).reset_index(drop=True)
    summary = summarize_annual_offer_costs(annual_offer_costs)

    return {
        "storage_dir": resolved_storage_dir,
        "profile_path": resolved_profile_path,
        "meter_data": meter_data,
        "consumption_summary": consumption["summary"],
        "monthly_usage_matrix": consumption["monthly_usage_matrix"].reset_index(),
        "annual_usage_vector": consumption["annual_usage_vector"].reset_index(),
        "snapshot_costs": pd.DataFrame(),
        "fixed_annual_offer_costs": fixed_annual_offer_costs,
        "variable_annual_offer_costs": variable_annual_offer_costs,
        "annual_offer_costs": annual_offer_costs,
        "latest_offer_costs": annual_offer_costs,
        "summary_by_contract_type": summary,
        **fixed_matrices,
        **variable_matrices,
    }
