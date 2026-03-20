from __future__ import annotations

import pandas as pd

from parquet_loader import (
    StorageFrames,
    build_contract_catalog,
    combine_fees,
    combine_usage,
)


def build_usage_analysis_table(frames: StorageFrames) -> pd.DataFrame:
    usage = combine_usage(frames)
    catalog = build_contract_catalog(frames)
    if usage.empty or catalog.empty:
        return pd.DataFrame()

    merged = usage.merge(
        catalog[
            [
                "contract_snapshot_key",
                "offer_key",
                "provider_name",
                "contract_type",
                "contract_base_name",
                "contract_duration_label",
                "meter_type",
                "has_gas",
                "has_electricity",
                "snapshot_month",
                "year",
            ]
        ],
        on="contract_snapshot_key",
        how="left",
        suffixes=("", "_contract"),
    )
    return merged


def build_fee_analysis_table(frames: StorageFrames) -> pd.DataFrame:
    fees = combine_fees(frames)
    catalog = build_contract_catalog(frames)
    if fees.empty or catalog.empty:
        return pd.DataFrame()

    merged = fees.merge(
        catalog[
            [
                "contract_snapshot_key",
                "offer_key",
                "provider_name",
                "contract_type",
                "contract_base_name",
                "contract_duration_label",
                "meter_type",
                "snapshot_month",
                "year",
            ]
        ],
        on="contract_snapshot_key",
        how="left",
        suffixes=("", "_contract"),
    )
    return merged


def filter_contract_catalog(
    catalog: pd.DataFrame,
    provider_names: list[str] | set[str] | None = None,
    contract_type: str | None = None,
    year: int | None = None,
) -> pd.DataFrame:
    if catalog.empty:
        return pd.DataFrame()

    filtered = catalog.copy()
    if provider_names:
        allowed = set(provider_names)
        filtered = filtered[filtered["provider_name"].isin(allowed)]
    if contract_type:
        filtered = filtered[filtered["contract_type"] == contract_type]
    if year is not None:
        filtered = filtered[filtered["year"] == year]
    return filtered


def pivot_usage_rates(
    usage_table: pd.DataFrame,
    provider_names: list[str] | set[str] | None = None,
    contract_type: str | None = None,
    year: int | None = None,
    commodity: str | None = None,
) -> pd.DataFrame:
    if usage_table.empty:
        return pd.DataFrame()

    filtered = usage_table.copy()
    if provider_names:
        filtered = filtered[filtered["provider_name"].isin(set(provider_names))]
    if contract_type:
        filtered = filtered[filtered["contract_type"] == contract_type]
    if year is not None:
        filtered = filtered[filtered["year"] == year]
    if commodity:
        filtered = filtered[filtered["commodity"] == commodity]

    if filtered.empty:
        return pd.DataFrame()

    pivot = filtered.pivot_table(
        values="rate",
        index="provider_name",
        columns=["contract_type", "commodity", "tariff_band"],
        aggfunc="mean",
    )
    return pivot.sort_index()


def pivot_fee_amounts(
    fee_table: pd.DataFrame,
    provider_names: list[str] | set[str] | None = None,
    contract_type: str | None = None,
    year: int | None = None,
) -> pd.DataFrame:
    if fee_table.empty:
        return pd.DataFrame()

    filtered = fee_table.copy()
    if provider_names:
        filtered = filtered[filtered["provider_name"].isin(set(provider_names))]
    if contract_type:
        filtered = filtered[filtered["contract_type"] == contract_type]
    if year is not None:
        filtered = filtered[filtered["year"] == year]

    if filtered.empty:
        return pd.DataFrame()

    annual_amount = filtered["annual_amount"].fillna(filtered["amount"])
    filtered = filtered.assign(annual_amount=annual_amount)
    pivot = filtered.pivot_table(
        values="annual_amount",
        index="provider_name",
        columns=["contract_type", "fee_component"],
        aggfunc="mean",
    )
    return pivot.sort_index()


def provider_year_overview(
    frames: StorageFrames,
    provider_names: list[str] | set[str] | None = None,
    year: int | None = None,
) -> dict[str, pd.DataFrame]:
    catalog = build_contract_catalog(frames)
    usage_table = build_usage_analysis_table(frames)
    fee_table = build_fee_analysis_table(frames)
    contracts = filter_contract_catalog(catalog, provider_names=provider_names, year=year)
    usage_pivot = pivot_usage_rates(usage_table, provider_names=provider_names, year=year)
    fee_pivot = pivot_fee_amounts(fee_table, provider_names=provider_names, year=year)
    return {
        "catalog": catalog,
        "usage_table": usage_table,
        "fee_table": fee_table,
        "contracts": contracts.sort_values(["provider_name", "contract_type", "snapshot_month"]),
        "usage_pivot": usage_pivot,
        "fee_pivot": fee_pivot,
    }
