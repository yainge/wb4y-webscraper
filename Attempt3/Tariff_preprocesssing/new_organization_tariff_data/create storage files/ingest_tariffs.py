#!/usr/bin/env python3
"""
Tariff ingestion pipeline for monthly Dutch energy contract snapshots.

This version keeps contract identity and contract grouping separate:
- `contract_snapshot_key` is the unique contract-snapshot identifier
- `contract_base_key` is a grouping key for normalized contract families

Feed-in lookup and feed-in tariff handling are intentionally excluded.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional, Tuple

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


logger = logging.getLogger(__name__)

DUTCH_MONTHS = {
    "januari": 1,
    "februari": 2,
    "maart": 3,
    "april": 4,
    "mei": 5,
    "juni": 6,
    "juli": 7,
    "augustus": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
}

MONTH_VARIANT_PATTERN = re.compile(
    r"\s+(?:jan|feb|mar|mrt|apr|mei|jun|juni|jul|juli|aug|augustus|sep|september|"
    r"okt|oktober|nov|november|dec|december)\s+\d{4}$",
    re.IGNORECASE,
)
MONTH_CODE_PATTERN = re.compile(r"\s+20\d{4}$")
DELTA_VARIANT_PATTERN = re.compile(r"\s+(\([a-z]\))$", re.IGNORECASE)
TRAILING_CODE_PATTERN = re.compile(r"^(.*?)(?:\s+)([A-Z]{1,3}|VP\d(?:-B)?)$")
PROMO_SUFFIXES = [
    "Welkom Terug",
    "Welkom",
    "Actie",
    "Voordeel",
    "met Loyaliteitsbonus",
    "met LB",
    "met korting",
    "met Korting",
    "Korting",
    "Energiekantoor.nl",
    "Hosted Energy",
    "klantenservice",
    "Bewind",
    "FM",
    "Ziggo",
    "ING Puntenaanbod",
]
PROMO_SUFFIX_PATTERNS = [
    re.compile(rf"^(.*?)(?:\s+|\s*-\s*)({re.escape(suffix)})$", re.IGNORECASE)
    for suffix in PROMO_SUFFIXES
]

CONTRACT_NAME_BASES_CACHE: Dict[str, Any] = {}


@dataclass
class ParsedMonth:
    year: int
    month: int

    @property
    def yyyy_mm(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


@dataclass
class NameNormalization:
    raw_contract_name: str
    contract_name_no_variant: str
    contract_name_no_variant_slug: str
    contract_base_name: str
    contract_base_slug: str
    contract_base_key: str
    variant: Optional[str]
    normalization_status: str
    normalization_rule: str


@dataclass
class ContractRow:
    contract_snapshot_key: str
    contract_base_key: str
    provider_id: str
    provider_name: str
    raw_contract_name: str
    contract_name_no_variant: str
    contract_name_no_variant_slug: str
    contract_base_name: str
    contract_base_slug: str
    variant: Optional[str]
    contract_type: str
    contract_duration_label: str
    duration_months: Optional[int]
    meter_type: str
    has_gas: bool
    has_electricity: bool
    snapshot_month: str
    source_file: str
    source_session_id: str
    source_tuple_id: str
    estimated_annual_costs: Optional[str]
    normalization_status: str
    normalization_rule: str
    is_active: bool = True


@dataclass
class UsageRow:
    usage_key: str
    contract_snapshot_key: str
    contract_base_key: str
    provider_id: str
    snapshot_month: str
    commodity: str
    direction: str
    tariff_band: str
    period: str
    rate: Decimal
    unit: str


@dataclass
class FeeRow:
    fee_key: str
    contract_snapshot_key: str
    contract_base_key: str
    provider_id: str
    snapshot_month: str
    fee_component: str
    amount: Decimal
    billing_frequency: Optional[str]
    annual_amount: Optional[Decimal]
    unit: str = "EUR"


@dataclass
class TransformationResult:
    contract_row: ContractRow
    usage_rows: List[UsageRow] = field(default_factory=list)
    fee_rows: List[FeeRow] = field(default_factory=list)


def setup_logging(level: int = logging.INFO) -> None:
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(level)


def slugify(value: str) -> str:
    if value is None:
        return "unknown"
    value = unicodedata.normalize("NFKD", str(value))
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "unknown"


def normalize_text(value: str) -> str:
    value = (value or "").strip()
    value = value.replace("\u2013", "-").replace("\u2014", "-")
    value = value.replace(" | ", " ")
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+\)", ")", value)
    value = re.sub(r"\(\s+", "(", value)
    value = re.sub(r"\s+/\s+", " / ", value)
    return value.strip()


def parse_dutch_decimal(value_str: str) -> Decimal:
    if value_str is None or value_str == "":
        raise ValueError("Cannot parse empty or None value")
    normalized = str(value_str).strip().replace(",", ".")
    try:
        return Decimal(normalized)
    except Exception as exc:
        raise ValueError(f"Cannot parse '{value_str}' as decimal: {exc}") from exc


def parse_dutch_month(month_str: str) -> ParsedMonth:
    parts = normalize_text(month_str).lower().split()
    if len(parts) != 2:
        raise ValueError(f"Expected 'month year', got '{month_str}'")
    month_name, year_str = parts
    if month_name not in DUTCH_MONTHS:
        raise ValueError(f"Unknown Dutch month name: '{month_name}'")
    return ParsedMonth(year=int(year_str), month=DUTCH_MONTHS[month_name])


def infer_snapshot_month(raw_record: Dict[str, Any], filepath: Path) -> ParsedMonth:
    month_idx = raw_record.get("_month_idx")
    if month_idx:
        try:
            return parse_dutch_month(month_idx)
        except ValueError as exc:
            logger.warning("Could not parse _month_idx '%s': %s", month_idx, exc)

    stem_lower = filepath.stem.lower()
    for month_name, month_num in DUTCH_MONTHS.items():
        match = re.search(rf"{month_name}\s+(\d{{4}})", stem_lower)
        if match:
            return ParsedMonth(year=int(match.group(1)), month=month_num)

    raise ValueError(
        f"Could not infer snapshot month from '{filepath.name}' "
        f"or _month_idx={raw_record.get('_month_idx')!r}"
    )


def classify_contract_type(contract_duration: str) -> str:
    duration_lower = normalize_text(contract_duration).lower()
    if "variabel" in duration_lower or "onbepaald" in duration_lower:
        return "variable"
    if "vast" in duration_lower:
        return "fixed"
    raise ValueError(
        f"Cannot classify contract type from duration '{contract_duration}'"
    )


def parse_duration_months(contract_duration: str) -> Optional[int]:
    duration_lower = normalize_text(contract_duration).lower()
    if "onbepaald" in duration_lower or "variabel" in duration_lower:
        return None
    if "halfjaar" in duration_lower or "6 maanden" in duration_lower:
        return 6
    if "kwartaal" in duration_lower or "3 maanden" in duration_lower:
        return 3

    year_match = re.search(r"(\d+)\s*(?:jaar|year|years)", duration_lower)
    if year_match:
        return int(year_match.group(1)) * 12

    month_match = re.search(r"(\d+)\s*(?:maand|maanden|month|months)", duration_lower)
    if month_match:
        return int(month_match.group(1))

    logger.warning("Could not parse duration from '%s'", contract_duration)
    return None


def normalize_provider_id(provider_name: str) -> str:
    normalized = normalize_text(provider_name).replace("&", " and ")
    return slugify(normalized)


def load_contract_reference_data() -> None:
    global CONTRACT_NAME_BASES_CACHE

    bases_file = Path(__file__).parent / "contract_name_bases.json"
    if bases_file.exists():
        with open(bases_file, "r", encoding="utf-8") as handle:
            CONTRACT_NAME_BASES_CACHE = json.load(handle)
        provider_count = len(
            [key for key in CONTRACT_NAME_BASES_CACHE.keys() if not key.startswith("_")]
        )
        logger.info("Loaded contract_name_bases.json for %s providers", provider_count)
    else:
        CONTRACT_NAME_BASES_CACHE = {}
        logger.warning("contract_name_bases.json not found at %s", bases_file)


def strip_snapshot_suffix(contract_name: str) -> str:
    name = normalize_text(contract_name)
    name = MONTH_VARIANT_PATTERN.sub("", name)
    name = MONTH_CODE_PATTERN.sub("", name)
    return normalize_text(name)


def extract_variant(contract_name: str) -> Tuple[str, Optional[str]]:
    name = strip_snapshot_suffix(contract_name)

    delta_match = DELTA_VARIANT_PATTERN.match(name)
    if delta_match:
        variant = delta_match.group(1)
        base = name[: -len(variant)].strip()
        return normalize_text(base), variant

    for pattern in PROMO_SUFFIX_PATTERNS:
        match = pattern.match(name)
        if match:
            return normalize_text(match.group(1)), normalize_text(match.group(2))

    code_match = TRAILING_CODE_PATTERN.match(name)
    if code_match:
        base = normalize_text(code_match.group(1))
        variant = code_match.group(2)
        if base:
            return base, variant

    return name, None


def remove_duration_tokens(value: str) -> str:
    text = normalize_text(value)
    patterns = [
        r"\b\d+\s+jaar\b",
        r"\b\d+\s+maand(?:en)?\b",
        r"\bhalfjaar\b",
        r"\bkwartaal\b",
        r"\bonbepaalde tijd\b",
        r"\bflexibele looptijd\b",
        r"\bvariabel\b",
        r"\bvaste prijs\b",
        r"\bvaste looptijd\b",
        r"\bvast\b",
        r"\bzeker\b",
        r"\bmaandelijks\b",
        r"\btot\s+\d{1,2}-\d{1,2}-\d{4}\b",
    ]
    for pattern in patterns:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\(\s*\)", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ,-")


def is_duration_only_base(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"(?:\d+\s+jaar(?:\s+(?:vast|variabel|zeker))?"
            r"|\d+\s+maand(?:en)?(?:\s+(?:vast|variabel|zeker))?"
            r"|halfjaar(?:\s+(?:vast|variabel|zeker))?"
            r"|kwartaal(?:\s+(?:vast|variabel|zeker))?"
            r"|variabel(?:\s+onbepaalde\s+tijd)?"
            r"|flexibel)",
            value.lower(),
        )
    )


def apply_reference_base(provider_name: str, contract_name_no_variant: str) -> Optional[str]:
    provider_config = CONTRACT_NAME_BASES_CACHE.get(provider_name)
    if not provider_config or "primary_bases" not in provider_config:
        return None

    name_slug = slugify(contract_name_no_variant)
    matches: List[Tuple[int, str]] = []
    for base in provider_config.get("primary_bases", []):
        base_slug = slugify(base)
        if not base_slug:
            continue
        if base_slug == name_slug or base_slug in name_slug:
            matches.append((len(base_slug), base))

    if not matches:
        return None

    matches.sort(reverse=True)
    return matches[0][1]


def derive_contract_base(
    provider_name: str,
    contract_name_no_variant: str,
    contract_type: Optional[str] = None,
    contract_duration_label: Optional[str] = None,
) -> Tuple[str, str, str]:
    name = normalize_text(contract_name_no_variant)
    lowered = name.lower()

    def provider_plus_duration_base() -> Optional[str]:
        if contract_duration_label:
            return normalize_text(f"{provider_name} {contract_duration_label}")
        if contract_type:
            return normalize_text(f"{provider_name} {contract_type}")
        return None

    if lowered == "modelcontract":
        return "Modelcontract", "shared_rule", "modelcontract"

    if re.fullmatch(r"\d+(?:,\d+)?", name):
        provider_duration = provider_plus_duration_base()
        if provider_duration:
            return (
                provider_duration,
                "shared_rule",
                "numeric_to_provider_duration",
            )
        return normalize_text(f"{provider_name} numeric contract"), "fallback", "numeric_without_duration"

    if lowered == "vaste einddatum":
        provider_duration = provider_plus_duration_base()
        if provider_duration:
            return (
                provider_duration,
                "shared_rule",
                "vaste_einddatum_to_provider_duration",
            )
        return normalize_text(f"{provider_name} Vaste Einddatum"), "fallback", "vaste_einddatum_without_duration"

    if is_duration_only_base(lowered):
        provider_duration = provider_plus_duration_base()
        if provider_duration:
            return (
                provider_duration,
                "shared_rule",
                "duration_only_to_provider_duration",
            )
        return normalize_text(f"{provider_name} {name}"), "fallback", "duration_only_without_duration"

    if provider_name == "Cleanenergy":
        match = re.search(
            r"Clean Energy(?:\s+(Huishoudelijk|Consument|Particulier|MKB|Zakelijk Groen Thuis|Zakelijk))?",
            name,
            re.IGNORECASE,
        )
        if match:
            return "Clean Energy", "provider_rule", "cleanenergy_base"
        if "particulier variabel" in lowered:
            return "Clean Energy", "provider_rule", "cleanenergy_base"

    if provider_name == "Coolblue Energie":
        if "ing puntenaanbod" in lowered:
            provider_duration = provider_plus_duration_base()
            if provider_duration:
                return provider_duration, "provider_rule", "coolblue_partner_offer_to_provider_duration"
        for base in ["Direct voordeel", "Minder energie", "Zeker", "Modelcontract"]:
            if slugify(base) in slugify(name):
                return base, "provider_rule", "coolblue_base"

    if provider_name == "DELTA energie":
        if "delta groene actiestroom" in lowered:
            return "DELTA Groene Actiestroom + DELTA Actiegas", "provider_rule", "delta_actie"
        if "delta puur zeeuws groen" in lowered:
            return "DELTA Puur Zeeuws Groen + DELTA MixGroen Gas", "provider_rule", "delta_zeeuws"
        if "delta groene stroom" in lowered:
            return "DELTA Groene Stroom + DELTA Gas", "provider_rule", "delta_standard"

    if provider_name == "Energiedirect.nl":
        if "groene stroom en gas" in lowered:
            return "Groene Stroom en Gas", "provider_rule", "energiedirect_bundle"
        cleaned = re.sub(r"^Vast\s+", "", name, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(ACQ|AFL|A|P)\b", " ", cleaned)
        cleaned = remove_duration_tokens(cleaned)
        cleaned = re.sub(r"\bEnergiecollectief\b", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bKlant\b", " ", cleaned, flags=re.IGNORECASE)
        cleaned = normalize_text(cleaned)
        return cleaned or name, "provider_rule", "energiedirect_cleanup"

    if provider_name == "Eneco":
        elec = "HollandseWind & Zon" if "hollandsewind" in lowered and "zon" in lowered else None
        gas = None
        if "co2-gecompenseerdgas" in lowered:
            gas = "CO2-GecompenseerdGas"
        elif re.search(r"\bgas\b", lowered):
            gas = "Gas"
        if elec and gas and "voordeelmomenten" in lowered:
            return f"VoordeelMomenten {elec} + {gas}", "provider_rule", "eneco_bundle"
        if elec and gas:
            return f"{elec} + {gas}", "provider_rule", "eneco_bundle"

    if provider_name == "Essent":
        if "groene stroom (nl) en gas" in lowered:
            return "Groene Stroom (NL) en Gas", "provider_rule", "essent_bundle"
        if "groene stroom en gas" in lowered:
            return "Groene Stroom en Gas", "provider_rule", "essent_bundle"

    if provider_name == "Engie retail":
        if "engie opgewekt" in lowered:
            return "ENGIE opgewekt", "provider_rule", "engie_opgewekt"
        if "engie open" in lowered:
            return "ENGIE Open", "provider_rule", "engie_open"

    if provider_name == "Frank energie":
        if "1 jaar vast" in lowered:
            return "Frank Energie 1 jaar vast", "provider_rule", "frank_fixed"
        if "variabel" in lowered:
            return "Frank Energie Variabel", "provider_rule", "frank_variable"

    if provider_name == "Hezelaer Energy":
        if "vastzeker" in lowered:
            return "VastZeker", "provider_rule", "hezelaer_vastzeker"

    if provider_name in {"Greenchoice", "Greenchoice Zakelijk"}:
        if "groenbezig" in slugify(name):
            return "Groen Bezig", "provider_rule", "greenchoice_groen_bezig"
        known_bases = [
            "100% Nederlandse Wind",
            "Nederlandse Windstroom",
            "Groen&Vrij Wind en Zon",
            "Groen & Vrij",
            "Groen Bezig",
            "Slimgroen",
            "Zonnestroom",
            "Zorgeloos Energie",
            "Collectief",
            "Greenchoice Zakelijk 100% NL Wind voor Echte Bakkers",
            "100% NL Wind",
            "Greenchoice",
        ]
        for base in known_bases:
            if slugify(base) in slugify(name):
                return base, "provider_rule", "greenchoice_known_base"

    if provider_name == "Mega":
        if re.fullmatch(r"\d+(?:,\d+)?", name):
            return name, "fallback", "mega_numeric_fallback"
        if "veh" in lowered:
            return "VEH", "provider_rule", "mega_veh"
        if "variabel maandelijks" in lowered:
            return "Variabel maandelijks", "provider_rule", "mega_variable"

    if provider_name == "Om | nieuwe energie":
        if lowered.startswith("flex"):
            return "Flex", "provider_rule", "om_flex"
        if lowered.startswith("variabel"):
            return "Variabel", "provider_rule", "om_variabel"
        if "1 jaar vast" in lowered:
            return "1 jaar vast", "provider_rule", "om_fixed"

    if provider_name == "UnitedConsumers":
        if lowered.startswith("regiokorting"):
            return "Regiokorting", "provider_rule", "uc_discount"
        if lowered.startswith("stapelkorting"):
            return "Stapelkorting", "provider_rule", "uc_discount"
        if "wind mee" in lowered:
            return "Wind mee", "provider_rule", "uc_wind_mee"
        if "vaste prijs" in lowered:
            return "vaste prijs", "provider_rule", "uc_vaste_prijs"
        if "variabel" in lowered:
            return "Variabel", "provider_rule", "uc_variabel"

    reference_base = apply_reference_base(provider_name, name)
    if reference_base:
        return reference_base, "reference", "primary_bases"

    fallback = remove_duration_tokens(name)
    fallback = re.sub(r"\+\s*\d+(?:,\d+)?\s*euro\b", " ", fallback, flags=re.IGNORECASE)
    fallback = re.sub(r"\b\d+(?:,\d+)?\s*euro\b", " ", fallback, flags=re.IGNORECASE)
    fallback = re.sub(r"\bmet korting\b", " ", fallback, flags=re.IGNORECASE)
    fallback = re.sub(r"\bkorting\b", " ", fallback, flags=re.IGNORECASE)
    fallback = re.sub(r"\bstart\b", " ", fallback, flags=re.IGNORECASE)
    fallback = re.sub(r"\s+\+\s+", " ", fallback)
    fallback = normalize_text(fallback)
    fallback = fallback.strip(" ,-+")

    if not fallback or fallback.lower() in {
        "met korting",
        "start",
        "met korting start",
        "variabel",
        "vaste einddatum",
    } or is_duration_only_base(fallback):
        provider_duration = provider_plus_duration_base()
        if provider_duration:
            return (
                provider_duration,
                "shared_rule",
                "generic_modifier_to_provider_duration",
            )
        return normalize_text(f"{provider_name} {name}"), "fallback", "generic_modifier_without_duration"

    return fallback, "fallback", "generic_cleanup"


def normalize_contract_name(
    provider_name: str,
    raw_contract_name: str,
    contract_type: Optional[str] = None,
    contract_duration_label: Optional[str] = None,
) -> NameNormalization:
    raw = normalize_text(raw_contract_name)
    no_variant, variant = extract_variant(raw)
    no_variant = normalize_text(no_variant)

    base_name, status, rule = derive_contract_base(
        provider_name,
        no_variant,
        contract_type=contract_type,
        contract_duration_label=contract_duration_label,
    )
    provider_id = normalize_provider_id(provider_name)
    base_slug = slugify(base_name)
    no_variant_slug = slugify(no_variant)

    return NameNormalization(
        raw_contract_name=raw,
        contract_name_no_variant=no_variant,
        contract_name_no_variant_slug=no_variant_slug,
        contract_base_name=base_name,
        contract_base_slug=base_slug,
        contract_base_key=f"{provider_id}|{base_slug}",
        variant=variant,
        normalization_status=status,
        normalization_rule=rule,
    )


def generate_contract_snapshot_key(
    provider_id: str,
    contract_type: str,
    meter_type: str,
    contract_name_no_variant_slug: str,
    contract_duration_label: str,
    variant: Optional[str],
    snapshot_month: str,
) -> str:
    duration_token = slugify(contract_duration_label)
    variant_token = slugify(variant) if variant else "none"
    parts = [
        provider_id,
        contract_type,
        meter_type,
        contract_name_no_variant_slug,
        duration_token,
        variant_token,
        snapshot_month,
    ]
    return "|".join(parts)


def generate_usage_key(
    contract_snapshot_key: str,
    commodity: str,
    direction: str,
    tariff_band: str,
    period: str,
) -> str:
    return "|".join([contract_snapshot_key, commodity, direction, tariff_band, period])


def generate_fee_key(contract_snapshot_key: str, fee_component: str) -> str:
    return "|".join([contract_snapshot_key, fee_component])


def parse_json_file(filepath: Path) -> List[Dict[str, Any]]:
    with open(filepath, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON list in {filepath}, got {type(data).__name__}")
    return data


def transform_contract(raw_record: Dict[str, Any], filepath: Path) -> TransformationResult:
    provider_name = normalize_text(raw_record.get("provider", ""))
    if not provider_name:
        raise ValueError("Missing 'provider' field")

    raw_contract_name = normalize_text(raw_record.get("contract_name", ""))
    if not raw_contract_name:
        raise ValueError("Missing 'contract_name' field")

    contract_duration = normalize_text(raw_record.get("contract_duration", ""))
    if not contract_duration:
        raise ValueError("Missing 'contract_duration' field")

    meter_type = normalize_text(raw_record.get("meter_type", "")).lower()
    if meter_type not in {"single", "double"}:
        raise ValueError(f"Invalid meter_type '{meter_type}'")

    tariffs = raw_record.get("tariffs")
    if not isinstance(tariffs, dict):
        raise ValueError("Expected 'tariffs' to be a dict")

    snapshot_month = infer_snapshot_month(raw_record, filepath)
    contract_type = classify_contract_type(contract_duration)
    duration_months = parse_duration_months(contract_duration)
    provider_id = normalize_provider_id(provider_name)
    normalized_name = normalize_contract_name(
        provider_name,
        raw_contract_name,
        contract_type=contract_type,
        contract_duration_label=contract_duration,
    )

    has_gas = isinstance(tariffs.get("gas"), dict)
    has_electricity = isinstance(tariffs.get("electricity"), dict)
    if not has_gas and not has_electricity:
        raise ValueError("Contract has neither gas nor electricity tariffs")

    contract_snapshot_key = generate_contract_snapshot_key(
        provider_id=provider_id,
        contract_type=contract_type,
        meter_type=meter_type,
        contract_name_no_variant_slug=normalized_name.contract_name_no_variant_slug,
        contract_duration_label=contract_duration,
        variant=normalized_name.variant,
        snapshot_month=snapshot_month.yyyy_mm,
    )

    contract_row = ContractRow(
        contract_snapshot_key=contract_snapshot_key,
        contract_base_key=normalized_name.contract_base_key,
        provider_id=provider_id,
        provider_name=provider_name,
        raw_contract_name=normalized_name.raw_contract_name,
        contract_name_no_variant=normalized_name.contract_name_no_variant,
        contract_name_no_variant_slug=normalized_name.contract_name_no_variant_slug,
        contract_base_name=normalized_name.contract_base_name,
        contract_base_slug=normalized_name.contract_base_slug,
        variant=normalized_name.variant,
        contract_type=contract_type,
        contract_duration_label=contract_duration,
        duration_months=duration_months,
        meter_type=meter_type,
        has_gas=has_gas,
        has_electricity=has_electricity,
        snapshot_month=snapshot_month.yyyy_mm,
        source_file=filepath.name,
        source_session_id=raw_record.get("_session_id", "unknown"),
        source_tuple_id=raw_record.get("_tupleId", "unknown"),
        estimated_annual_costs=raw_record.get("estimated_annual_costs"),
        normalization_status=normalized_name.normalization_status,
        normalization_rule=normalized_name.normalization_rule,
    )

    usage_rows: List[UsageRow] = []
    fee_rows: List[FeeRow] = []
    period = snapshot_month.yyyy_mm if contract_type == "variable" else "year"

    if has_electricity:
        elec_tariffs = tariffs["electricity"]

        fixed_yearly = elec_tariffs.get("fixed_yearly")
        if fixed_yearly not in (None, ""):
            amount = parse_dutch_decimal(fixed_yearly)
            fee_rows.append(
                FeeRow(
                    fee_key=generate_fee_key(contract_snapshot_key, "electricity_supplier_fee"),
                    contract_snapshot_key=contract_snapshot_key,
                    contract_base_key=normalized_name.contract_base_key,
                    provider_id=provider_id,
                    snapshot_month=snapshot_month.yyyy_mm,
                    fee_component="electricity_supplier_fee",
                    amount=amount,
                    billing_frequency="yearly" if contract_type == "variable" else None,
                    annual_amount=amount,
                )
            )

        piek = elec_tariffs.get("piek_per_kwh")
        dal = elec_tariffs.get("dal_per_kwh")

        if meter_type == "single" and piek not in (None, ""):
            rate = parse_dutch_decimal(piek)
            usage_rows.append(
                UsageRow(
                    usage_key=generate_usage_key(
                        contract_snapshot_key,
                        "electricity",
                        "import",
                        "single",
                        period,
                    ),
                    contract_snapshot_key=contract_snapshot_key,
                    contract_base_key=normalized_name.contract_base_key,
                    provider_id=provider_id,
                    snapshot_month=snapshot_month.yyyy_mm,
                    commodity="electricity",
                    direction="import",
                    tariff_band="single",
                    period=period,
                    rate=rate,
                    unit="kWh",
                )
            )

        if meter_type == "double":
            if piek not in (None, ""):
                peak_rate = parse_dutch_decimal(piek)
                usage_rows.append(
                    UsageRow(
                        usage_key=generate_usage_key(
                            contract_snapshot_key,
                            "electricity",
                            "import",
                            "peak",
                            period,
                        ),
                        contract_snapshot_key=contract_snapshot_key,
                        contract_base_key=normalized_name.contract_base_key,
                        provider_id=provider_id,
                        snapshot_month=snapshot_month.yyyy_mm,
                        commodity="electricity",
                        direction="import",
                        tariff_band="peak",
                        period=period,
                        rate=peak_rate,
                        unit="kWh",
                    )
                )
            if dal not in (None, ""):
                offpeak_rate = parse_dutch_decimal(dal)
                usage_rows.append(
                    UsageRow(
                        usage_key=generate_usage_key(
                            contract_snapshot_key,
                            "electricity",
                            "import",
                            "offpeak",
                            period,
                        ),
                        contract_snapshot_key=contract_snapshot_key,
                        contract_base_key=normalized_name.contract_base_key,
                        provider_id=provider_id,
                        snapshot_month=snapshot_month.yyyy_mm,
                        commodity="electricity",
                        direction="import",
                        tariff_band="offpeak",
                        period=period,
                        rate=offpeak_rate,
                        unit="kWh",
                    )
                )

    if has_gas:
        gas_tariffs = tariffs["gas"]

        fixed_yearly = gas_tariffs.get("fixed_yearly")
        if fixed_yearly not in (None, ""):
            amount = parse_dutch_decimal(fixed_yearly)
            fee_rows.append(
                FeeRow(
                    fee_key=generate_fee_key(contract_snapshot_key, "gas_supplier_fee"),
                    contract_snapshot_key=contract_snapshot_key,
                    contract_base_key=normalized_name.contract_base_key,
                    provider_id=provider_id,
                    snapshot_month=snapshot_month.yyyy_mm,
                    fee_component="gas_supplier_fee",
                    amount=amount,
                    billing_frequency="yearly" if contract_type == "variable" else None,
                    annual_amount=amount,
                )
            )

        variable_per_m3 = gas_tariffs.get("variable_per_m3")
        if variable_per_m3 not in (None, ""):
            rate = parse_dutch_decimal(variable_per_m3)
            usage_rows.append(
                UsageRow(
                    usage_key=generate_usage_key(
                        contract_snapshot_key,
                        "gas",
                        "import",
                        "single",
                        period,
                    ),
                    contract_snapshot_key=contract_snapshot_key,
                    contract_base_key=normalized_name.contract_base_key,
                    provider_id=provider_id,
                    snapshot_month=snapshot_month.yyyy_mm,
                    commodity="gas",
                    direction="import",
                    tariff_band="single",
                    period=period,
                    rate=rate,
                    unit="m3",
                )
            )

    return TransformationResult(
        contract_row=contract_row,
        usage_rows=usage_rows,
        fee_rows=fee_rows,
    )


def dataclass_to_dict(obj: Any) -> Dict[str, Any]:
    record = asdict(obj)
    for key, value in list(record.items()):
        if isinstance(value, Decimal):
            record[key] = float(value)
    return record


def write_or_merge_parquet(
    output_path: Path,
    new_rows: List[Any],
    schema: pa.Schema,
    dedup_keys: List[str],
) -> int:
    if not new_rows:
        logger.info("No new rows for %s, skipping write", output_path.name)
        return 0

    new_df = pd.DataFrame([dataclass_to_dict(row) for row in new_rows])
    for field in schema:
        if field.name not in new_df.columns:
            new_df[field.name] = None

    if output_path.exists():
        existing_df = pq.read_table(output_path).to_pandas()
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        combined_df = new_df

    before = len(combined_df)
    combined_df = combined_df.drop_duplicates(subset=dedup_keys, keep="last")
    after = len(combined_df)
    if after != before:
        logger.info(
            "Deduplicated %s: %s -> %s rows",
            output_path.name,
            before,
            after,
        )

    combined_df = combined_df[[field.name for field in schema]]
    table = pa.Table.from_pandas(combined_df, schema=schema, preserve_index=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, output_path)
    logger.info("Wrote %s rows to %s", after, output_path)
    return after


def get_contracts_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("contract_snapshot_key", pa.string()),
            pa.field("contract_base_key", pa.string()),
            pa.field("provider_id", pa.string()),
            pa.field("provider_name", pa.string()),
            pa.field("raw_contract_name", pa.string()),
            pa.field("contract_name_no_variant", pa.string()),
            pa.field("contract_name_no_variant_slug", pa.string()),
            pa.field("contract_base_name", pa.string()),
            pa.field("contract_base_slug", pa.string()),
            pa.field("variant", pa.string(), nullable=True),
            pa.field("contract_type", pa.string()),
            pa.field("contract_duration_label", pa.string()),
            pa.field("duration_months", pa.int32(), nullable=True),
            pa.field("meter_type", pa.string()),
            pa.field("has_gas", pa.bool_()),
            pa.field("has_electricity", pa.bool_()),
            pa.field("snapshot_month", pa.string()),
            pa.field("source_file", pa.string()),
            pa.field("source_session_id", pa.string()),
            pa.field("source_tuple_id", pa.string()),
            pa.field("estimated_annual_costs", pa.string(), nullable=True),
            pa.field("normalization_status", pa.string()),
            pa.field("normalization_rule", pa.string()),
            pa.field("is_active", pa.bool_()),
        ]
    )


def get_usage_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("usage_key", pa.string()),
            pa.field("contract_snapshot_key", pa.string()),
            pa.field("contract_base_key", pa.string()),
            pa.field("provider_id", pa.string()),
            pa.field("snapshot_month", pa.string()),
            pa.field("commodity", pa.string()),
            pa.field("direction", pa.string()),
            pa.field("tariff_band", pa.string()),
            pa.field("period", pa.string()),
            pa.field("rate", pa.float64()),
            pa.field("unit", pa.string()),
        ]
    )


def get_fees_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("fee_key", pa.string()),
            pa.field("contract_snapshot_key", pa.string()),
            pa.field("contract_base_key", pa.string()),
            pa.field("provider_id", pa.string()),
            pa.field("snapshot_month", pa.string()),
            pa.field("fee_component", pa.string()),
            pa.field("amount", pa.float64()),
            pa.field("billing_frequency", pa.string(), nullable=True),
            pa.field("annual_amount", pa.float64(), nullable=True),
            pa.field("unit", pa.string()),
        ]
    )


def scan_input_files(input_root: Path, year: Optional[int] = None) -> List[Path]:
    input_root = Path(input_root)

    if year is not None:
        year_dir = input_root / str(year)
        if not year_dir.exists():
            raise FileNotFoundError(f"Year directory does not exist: {year_dir}")
        files = sorted(year_dir.glob("contracts_*.json"))
        logger.info("Found %s contract files in %s", len(files), year_dir)
        return files

    if input_root.name.isdigit() and len(input_root.name) == 4:
        files = sorted(input_root.glob("contracts_*.json"))
        logger.info("Found %s contract files in %s", len(files), input_root)
        return files

    direct_files = sorted(input_root.glob("contracts_*.json"))
    if direct_files:
        logger.info("Found %s contract files in %s", len(direct_files), input_root)
        return direct_files

    files: List[Path] = []
    for child in sorted(input_root.iterdir()):
        if child.is_dir() and child.name.isdigit() and len(child.name) == 4:
            files.extend(sorted(child.glob("contracts_*.json")))

    logger.info("Found %s contract files in year folders under %s", len(files), input_root)
    return files


def build_unmatched_review_payload(
    unmatched_records: DefaultDict[str, DefaultDict[str, Dict[str, Any]]],
    input_root: Path,
    year: Optional[int],
) -> Dict[str, Any]:
    providers: Dict[str, List[Dict[str, Any]]] = {}
    total = 0

    for provider_name, contracts in sorted(unmatched_records.items()):
        provider_entries: List[Dict[str, Any]] = []
        for raw_name, payload in sorted(
            contracts.items(),
            key=lambda item: (-item[1]["count"], item[0]),
        ):
            entry = {
                "raw_contract_name": raw_name,
                "count": payload["count"],
                "contract_name_no_variant": payload["contract_name_no_variant"],
                "contract_base_name": payload["contract_base_name"],
                "normalization_rule": payload["normalization_rule"],
                "snapshot_months": sorted(payload["snapshot_months"]),
                "source_files": sorted(payload["source_files"]),
            }
            provider_entries.append(entry)
            total += payload["count"]
        providers[provider_name] = provider_entries

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "input_root": str(Path(input_root).resolve()),
        "year_filter": year,
        "total_unmatched_records": total,
        "provider_count": len(providers),
        "providers": providers,
    }


def write_unmatched_review_json(
    output_root: Path,
    unmatched_records: DefaultDict[str, DefaultDict[str, Dict[str, Any]]],
    input_root: Path,
    year: Optional[int],
) -> None:
    payload = build_unmatched_review_payload(unmatched_records, input_root, year)
    output_path = Path(output_root) / "unmatched_contract_names.json"
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    logger.info("Wrote unmatched contract review to %s", output_path)


def ingest_all_contracts(input_root: Path, output_root: Path, year: Optional[int]) -> Dict[str, int]:
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    json_files = scan_input_files(input_root, year=year)
    if not json_files:
        logger.warning("No contract JSON files found for %s", input_root)
        return {"processed": 0, "skipped": 0, "errors": 0}

    fixed_contracts: List[ContractRow] = []
    fixed_usage: List[UsageRow] = []
    fixed_fees: List[FeeRow] = []
    variable_contracts: List[ContractRow] = []
    variable_usage: List[UsageRow] = []
    variable_fees: List[FeeRow] = []

    unmatched_records: DefaultDict[str, DefaultDict[str, Dict[str, Any]]] = defaultdict(
        lambda: defaultdict(
            lambda: {
                "count": 0,
                "contract_name_no_variant": "",
                "contract_base_name": "",
                "normalization_rule": "",
                "snapshot_months": set(),
                "source_files": set(),
            }
        )
    )

    stats = {"processed": 0, "skipped": 0, "errors": 0}

    for json_file in json_files:
        logger.info("Processing %s", json_file)
        try:
            raw_records = parse_json_file(json_file)
        except Exception as exc:
            logger.error("Failed to parse %s: %s", json_file, exc)
            stats["errors"] += 1
            continue

        for idx, raw_record in enumerate(raw_records):
            try:
                result = transform_contract(raw_record, json_file)
                stats["processed"] += 1

                if result.contract_row.normalization_status == "fallback":
                    bucket = unmatched_records[
                        result.contract_row.provider_name
                    ][result.contract_row.raw_contract_name]
                    bucket["count"] += 1
                    bucket["contract_name_no_variant"] = result.contract_row.contract_name_no_variant
                    bucket["contract_base_name"] = result.contract_row.contract_base_name
                    bucket["normalization_rule"] = result.contract_row.normalization_rule
                    bucket["snapshot_months"].add(result.contract_row.snapshot_month)
                    bucket["source_files"].add(result.contract_row.source_file)

                if result.contract_row.contract_type == "fixed":
                    fixed_contracts.append(result.contract_row)
                    fixed_usage.extend(result.usage_rows)
                    fixed_fees.extend(result.fee_rows)
                else:
                    variable_contracts.append(result.contract_row)
                    variable_usage.extend(result.usage_rows)
                    variable_fees.extend(result.fee_rows)

            except ValueError as exc:
                logger.warning("Skipped record %s in %s: %s", idx, json_file.name, exc)
                stats["skipped"] += 1
            except Exception as exc:
                logger.error(
                    "Unexpected error processing record %s in %s: %s",
                    idx,
                    json_file.name,
                    exc,
                    exc_info=True,
                )
                stats["errors"] += 1

    stats["fixed_contracts"] = write_or_merge_parquet(
        output_root / "contracts_fixed.parquet",
        fixed_contracts,
        get_contracts_schema(),
        dedup_keys=["contract_snapshot_key"],
    )
    stats["variable_contracts"] = write_or_merge_parquet(
        output_root / "contracts_variable.parquet",
        variable_contracts,
        get_contracts_schema(),
        dedup_keys=["contract_snapshot_key"],
    )
    stats["fixed_usage"] = write_or_merge_parquet(
        output_root / "fixed_usage.parquet",
        fixed_usage,
        get_usage_schema(),
        dedup_keys=["usage_key"],
    )
    stats["variable_usage"] = write_or_merge_parquet(
        output_root / "variable_usage.parquet",
        variable_usage,
        get_usage_schema(),
        dedup_keys=["usage_key"],
    )
    stats["fixed_fees"] = write_or_merge_parquet(
        output_root / "fixed_fees.parquet",
        fixed_fees,
        get_fees_schema(),
        dedup_keys=["fee_key"],
    )
    stats["variable_fees"] = write_or_merge_parquet(
        output_root / "variable_fees.parquet",
        variable_fees,
        get_fees_schema(),
        dedup_keys=["fee_key"],
    )

    write_unmatched_review_json(output_root, unmatched_records, input_root, year)
    return stats


def print_summary(stats: Dict[str, int]) -> None:
    logger.info("=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    logger.info("Records processed:  %s", stats.get("processed", 0))
    logger.info("Records skipped:    %s", stats.get("skipped", 0))
    logger.info("Processing errors:  %s", stats.get("errors", 0))
    logger.info("contracts_fixed.parquet:    %s", stats.get("fixed_contracts", 0))
    logger.info("contracts_variable.parquet: %s", stats.get("variable_contracts", 0))
    logger.info("fixed_usage.parquet:        %s", stats.get("fixed_usage", 0))
    logger.info("variable_usage.parquet:     %s", stats.get("variable_usage", 0))
    logger.info("fixed_fees.parquet:         %s", stats.get("fixed_fees", 0))
    logger.info("variable_fees.parquet:      %s", stats.get("variable_fees", 0))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest Dutch contract snapshots into normalized parquet storage."
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        required=True,
        help="Year folder (e.g. Attempt3/2025) or a root that contains year folders.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="Directory for output parquet and review JSON files.",
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Optional explicit year filter when --input-root points to a broader root.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args()

    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    load_contract_reference_data()

    if not args.input_root.exists():
        logger.error("Input directory does not exist: %s", args.input_root)
        return 1

    logger.info("=" * 70)
    logger.info("Tariff Ingestion Pipeline")
    logger.info("=" * 70)
    logger.info("Input root:  %s", args.input_root.resolve())
    logger.info("Output root: %s", args.output_root.resolve())
    if args.year is not None:
        logger.info("Year filter: %s", args.year)

    try:
        stats = ingest_all_contracts(args.input_root, args.output_root, args.year)
    except Exception as exc:
        logger.error("Fatal error during ingestion: %s", exc, exc_info=True)
        return 1

    print_summary(stats)
    logger.info("Ingestion complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
