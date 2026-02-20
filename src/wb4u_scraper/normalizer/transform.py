from __future__ import annotations

from datetime import datetime
from typing import Any
import json

import structlog

from wb4u_scraper.models.price_observation import PriceObservation
from wb4u_scraper.models.run_metadata import RunMetadata
from wb4u_scraper.normalizer.field_mapper import (
    infer_meter_direction,
    infer_tou_from_columns,
    map_columns,
    normalize_commodity,
    normalize_contract_type,
)
from wb4u_scraper.utils.hashing import content_hash_for_observation

logger = structlog.get_logger()


def normalize_raw_snapshot(
    worksheets: dict[str, list[dict[str, Any]]],
    scraped_at_utc: str,
) -> list[PriceObservation]:
    """Transform all worksheets from a raw snapshot into a flat list of PriceObservations."""
    records: list[PriceObservation] = []

    for ws_name, rows in worksheets.items():
        if not rows:
            continue

        col_mapping = map_columns(list(rows[0].keys()))

        logger.info(
            "normalizing_worksheet",
            worksheet=ws_name,
            row_count=len(rows),
            mapped_columns=col_mapping,
        )

        for row in rows:
            try:
                row_records = _normalize_single_row(
                    row=row,
                    col_mapping=col_mapping,
                    worksheet_name=ws_name,
                    scraped_at=scraped_at_utc,
                )
                records.extend(row_records)
            except Exception as exc:
                logger.warning(
                    "row_normalization_failed",
                    worksheet=ws_name,
                    error=str(exc),
                    row_preview=str(row)[:200],
                )

    logger.info("normalization_complete", total_records=len(records))
    return records


def _normalize_single_row(
    row: dict[str, Any],
    col_mapping: dict[str, str],
    worksheet_name: str,
    scraped_at: str,
) -> list[PriceObservation]:
    """Normalize a single raw row into one or more PriceObservations."""
    # Separate mapped vs unmapped fields
    mapped: dict[str, Any] = {}
    for raw_col, value in row.items():
        canonical = col_mapping.get(raw_col)
        if canonical:
            mapped[canonical] = value

    provider = str(mapped.get("provider_name", "")).strip()
    contract_name = str(mapped.get("contract_name", "")).strip()
    contract_type = normalize_contract_type(str(mapped.get("contract_type", "")))
    valid_from = _parse_date(mapped.get("valid_from"))
    commodity_raw = str(mapped.get("commodity", ""))
    commodity = normalize_commodity(commodity_raw) if commodity_raw else "electricity"

    source_fields_json = json.dumps(row, default=str, ensure_ascii=False)

    records: list[PriceObservation] = []

    # Primary price value
    value = _safe_float(mapped.get("value"))
    if value is not None and provider:
        unit = _infer_unit(commodity, mapped.get("unit_raw", ""))
        tou = infer_tou_from_columns(worksheet_name)
        direction = infer_meter_direction(worksheet_name)

        obs_dict = dict(
            provider_name=provider,
            contract_name=contract_name,
            contract_type=contract_type,
            commodity=commodity,
            meter_direction=direction,
            tou=tou,
            unit=unit,
            valid_from=valid_from,
            value=value,
        )

        records.append(
            PriceObservation(
                scraped_at_utc=scraped_at,
                valid_from=valid_from,
                provider_name=provider,
                contract_name=contract_name,
                contract_type=contract_type,
                commodity=commodity,
                meter_direction=direction,
                tou=tou,
                unit=unit,
                value=value,
                source_fields=source_fields_json,
                content_hash=content_hash_for_observation(obs_dict),
            )
        )

    # Fixed cost as separate record
    fixed_cost = _safe_float(mapped.get("fixed_cost_value"))
    if fixed_cost is not None and provider:
        fc_dict = dict(
            provider_name=provider,
            contract_name=contract_name,
            contract_type=contract_type,
            commodity=commodity,
            meter_direction="consumption",
            tou="flat",
            unit="eur_per_month",
            valid_from=valid_from,
            value=fixed_cost,
        )

        records.append(
            PriceObservation(
                scraped_at_utc=scraped_at,
                valid_from=valid_from,
                provider_name=provider,
                contract_name=contract_name,
                contract_type=contract_type,
                commodity=commodity,
                meter_direction="consumption",
                tou="flat",
                unit="eur_per_month",
                value=fixed_cost,
                source_fields=source_fields_json,
                content_hash=content_hash_for_observation(fc_dict),
            )
        )

    return records


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        f = float(str(val).replace(",", ".").replace("€", "").replace(" ", "").strip())
        return f
    except (ValueError, TypeError):
        return None


def _parse_date(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y-%m", "%B %Y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m")
        except ValueError:
            continue
    # Try extracting YYYY-MM pattern
    import re

    match = re.search(r"(\d{4})-(\d{2})", s)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return s


def _infer_unit(commodity: str, unit_raw: str) -> str:
    if unit_raw:
        lower = unit_raw.lower()
        if "kwh" in lower:
            return "eur_per_kwh"
        if "m3" in lower or "m³" in lower:
            return "eur_per_m3"
        if "gj" in lower:
            return "eur_per_gj"
        if "maand" in lower or "month" in lower:
            return "eur_per_month"
    if commodity == "gas":
        return "eur_per_m3"
    if commodity == "district_heating":
        return "eur_per_gj"
    return "eur_per_kwh"
