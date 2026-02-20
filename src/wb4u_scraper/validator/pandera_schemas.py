from __future__ import annotations

import pandera as pa
from pandera import Check, Column, DataFrameSchema

normalized_schema = DataFrameSchema(
    columns={
        "source": Column(str, Check.str_length(min_value=1)),
        "scraped_at_utc": Column(str, Check.str_length(min_value=10)),
        "valid_from": Column(str, nullable=True),
        "valid_to": Column(str, nullable=True),
        "country": Column(str, Check.isin(["NL"])),
        "provider_name": Column(str, Check.str_length(min_value=1)),
        "contract_name": Column(str),
        "contract_type": Column(str, Check.isin(["fixed", "variable", "dynamic", "hybrid", "model", "unknown"])),
        "commodity": Column(str, Check.isin(["electricity", "gas", "district_heating"])),
        "meter_direction": Column(str, Check.isin(["consumption", "feed_in"])),
        "tou": Column(str, Check.isin(["on_peak", "off_peak", "flat", "unknown"])),
        "unit": Column(str, Check.isin(["eur_per_kwh", "eur_per_m3", "eur_per_gj", "eur_per_month"])),
        "value": Column(float, Check.in_range(-5.0, 10.0)),
        "currency": Column(str, Check.isin(["EUR"])),
        "is_all_in": Column(bool),
        "notes": Column(str),
        "source_fields": Column(str),
        "content_hash": Column(str),
    },
    coerce=True,
)
