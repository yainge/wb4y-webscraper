from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Optional
import json


ContractType = Literal["fixed", "variable", "dynamic", "hybrid", "model", "unknown"]
Commodity = Literal["electricity", "gas", "district_heating"]
MeterDirection = Literal["consumption", "feed_in"]
TimeOfUse = Literal["on_peak", "off_peak", "flat", "unknown"]
Unit = Literal["eur_per_kwh", "eur_per_m3", "eur_per_gj", "eur_per_month"]


@dataclass(frozen=True)
class PriceObservation:
    """One atomic contract price observation. Immutable for safety."""

    source: str = "tableau_acm_price_monitor"
    scraped_at_utc: str = ""
    valid_from: Optional[str] = None  # YYYY-MM or YYYY-MM-DD
    valid_to: Optional[str] = None
    country: str = "NL"
    provider_name: str = ""
    contract_name: str = ""
    contract_type: ContractType = "unknown"
    commodity: Commodity = "electricity"
    meter_direction: MeterDirection = "consumption"
    tou: TimeOfUse = "unknown"
    unit: Unit = "eur_per_kwh"
    value: float = 0.0
    currency: str = "EUR"
    is_all_in: bool = True
    price_includes: Optional[str] = None  # e.g. "energy+tax+vat"
    notes: str = ""
    source_fields: str = "{}"  # JSON blob of original Tableau fields
    content_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def source_fields_parsed(self) -> dict[str, Any]:
        return json.loads(self.source_fields)
