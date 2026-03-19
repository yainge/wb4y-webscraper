#!/usr/bin/env python3
"""
Production-ready ETL script for Dutch energy contract tariff ingestion.

Transforms monthly raw JSON contract files into normalized parquet files
suitable for calculation engines. Supports incremental appends with
automatic deduplication.

Key features:
- Reads Dutch month-indexed JSON contract snapshots
- Handles comma-separated decimal numbers (Dutch locale)
- Normalizes providers, contracts, and durations
- Generates stable contract keys for idempotent operations
- Separates fixed and variable contracts
- Supports meter type variations (single/double)
- Writes append-safe parquet with built-in deduplication
- Extensible design for future feed-in tariff support
- Comprehensive logging and validation

Usage:
    python ingest_tariffs.py --input-root ./raw_contracts --output-root ./tariffs_curated
"""

import json
import logging
import sys
import re
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any, Tuple, Set
from datetime import datetime
from decimal import Decimal
import argparse

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from feed_in_lookup import (
    load_feed_in_tariffs,
    normalize_provider_name,
    normalize_contract_duration,
    get_feed_in_tariff,
)


# ============================================================================
# CONFIGURATION & LOGGING
# ============================================================================

logger = logging.getLogger(__name__)

# Dutch month name to month number mapping
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

# ============================================================================
# FEED-IN TARIFF GLOBAL CACHE
# ============================================================================
# These are loaded at pipeline startup and cached for performance
FEEDIN_TARIFFS_CACHE: Optional[Dict[str, Any]] = None
FEEDIN_METHODS_CACHE: Optional[Dict[str, Any]] = None

# Duration mapping for feed-in lookup normalization
DURATION_MAPPING = {
    # Keys: normalized duration tuples (type, months)
    # Values: standard feed-in lookup keys
    ("fixed", 12): "fixed_1year",
    ("fixed", 24): "fixed_2year",
    ("fixed", 36): "fixed_3year",
    ("fixed", 48): "fixed_4year",
    ("variable", None): "variable",
    ("variable", 0): "variable",
}


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class ParsedMonth:
    """Normalized month representation."""
    year: int
    month: int

    @property
    def yyyy_mm(self) -> str:
        """Return standardized YYYY-MM format."""
        return f"{self.year:04d}-{self.month:02d}"

    def __str__(self) -> str:
        return self.yyyy_mm


@dataclass
class ContractRow:
    """A single row for contracts.parquet."""
    contract_key: str
    provider_id: str
    provider_name: str
    contract_name: str
    contract_name_base: str  # Base contract name (product prefix removed, duration suffix removed)
    contract_name_slug: str  # URL-safe slug for deduplication/keys
    variant: Optional[str]  # Extracted variant (A, B, C, BAT, etc.) or None
    contract_type: str  # "fixed" or "variable"
    contract_duration_label: str
    duration_months: Optional[int]
    meter_type: str  # "single" or "double"
    has_gas: bool
    has_feed_in_tariff: bool
    has_feedin_tiers: bool
    feed_in_calculation_method: Optional[str]  # fixed_rate_per_kwh, tiered_staffels, etc.
    feed_in_rate_per_kwh: Optional[float]  # For fixed-rate providers
    snapshot_month: str  # "YYYY-MM"
    source_file: str
    source_session_id: str
    source_tuple_id: str
    estimated_annual_costs: Optional[str]
    is_active: bool = True


@dataclass
class UsageRow:
    """A single row for fixed_usage.parquet or variable_usage.parquet."""
    contract_key: str
    provider_id: str
    snapshot_month: str  # "YYYY-MM"
    commodity: str  # "electricity" or "gas"
    direction: str  # "import" for now, extensible for "feed_in"
    tariff_band: str  # "single", "peak", "offpeak"
    period: str  # "year" for fixed, "YYYY-MM" for variable
    rate: Decimal
    unit: str  # "kWh" or "m3"


@dataclass
class FeeRow:
    """A single row for fixed_fees.parquet or variable_fees.parquet."""
    contract_key: str
    provider_id: str
    snapshot_month: str
    fee_component: str  # e.g., "gas_supplier_fee", "electricity_supplier_fee"
    amount: Decimal
    billing_frequency: Optional[str] = None  # e.g., "yearly", None for fixed
    annual_amount: Optional[Decimal] = None
    unit: str = "EUR"


@dataclass
class FeedinTierRow:
    """A single row for fixed_feedin_tiers.parquet or variable_feedin_tiers.parquet."""
    contract_key: str
    provider_id: str
    snapshot_month: str
    settlement_period: str  # e.g., "quarter", "month"
    basis_type: str  # e.g., "net_production", "gross_production"
    tier_index: int
    tier_min_kwh: Optional[Decimal]
    tier_max_kwh: Optional[Decimal]
    tier_amount: Decimal
    unit: str = "EUR/kWh"
    vat_included: bool = False


@dataclass
class TransformationResult:
    """Accumulator for transformed data from a single contract."""
    contract_row: ContractRow
    usage_rows: List[UsageRow] = field(default_factory=list)
    fee_rows: List[FeeRow] = field(default_factory=list)
    feedin_tier_rows: List[FeedinTierRow] = field(default_factory=list)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def setup_logging(level: int = logging.INFO) -> None:
    """Configure logging with timestamps and clear formatting."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(level)


def load_feedin_tariffs(feedin_dir: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Load feed-in tariff JSON files into cache.
    
    Args:
        feedin_dir: Directory containing feed-in JSON files
    
    Returns:
        Tuple of (tariffs_dict, methods_dict)
    
    Raises:
        FileNotFoundError: if feed-in JSON files not found
    """
    global FEEDIN_TARIFFS_CACHE, FEEDIN_METHODS_CACHE
    
    if FEEDIN_TARIFFS_CACHE is not None and FEEDIN_METHODS_CACHE is not None:
        logger.debug("Using cached feed-in tariff data")
        return FEEDIN_TARIFFS_CACHE, FEEDIN_METHODS_CACHE
    
    tariffs_path = feedin_dir / "feed_in_tariffs.json"
    methods_path = feedin_dir / "feed_in_tariff_methods.json"
    
    if not tariffs_path.exists():
        raise FileNotFoundError(f"Feed-in tariffs file not found: {tariffs_path}")
    if not methods_path.exists():
        raise FileNotFoundError(f"Feed-in methods file not found: {methods_path}")
    
    logger.info(f"Loading feed-in tariff data from {feedin_dir}")
    
    with open(tariffs_path, "r", encoding="utf-8") as f:
        tariffs = json.load(f)
    
    with open(methods_path, "r", encoding="utf-8") as f:
        methods = json.load(f)
    
    FEEDIN_TARIFFS_CACHE = tariffs
    FEEDIN_METHODS_CACHE = methods
    
    logger.info(f"Loaded {len(tariffs.get('fixed_and_variable_contracts', {}))} fixed/variable providers")
    return tariffs, methods


def normalize_duration_for_lookup(
    contract_type: str,
    duration_months: Optional[int]
) -> str:
    """
    Normalize contract duration to standard feed-in lookup key.
    
    Maps (contract_type, duration_months) tuples to standardized keys used in feed-in data.
    
    Args:
        contract_type: "fixed" or "variable"
        duration_months: Number of months (12, 24, 36, etc.) or None for variable
    
    Returns:
        Standard lookup key (e.g., "fixed_1year", "variable")
    
    Examples:
        (fixed, 12) -> "fixed_1year"
        (fixed, 36) -> "fixed_3year"
        (variable, None) -> "variable"
    """
    lookup_key = (contract_type, duration_months)
    
    if lookup_key in DURATION_MAPPING:
        return DURATION_MAPPING[lookup_key]
    
    # Fallback for unknown durations
    if contract_type == "variable":
        logger.warning(f"Unknown variable duration {duration_months}, using 'variable' as fallback")
        return "variable"
    else:
        # For fixed contracts with unknown duration, try to find closest available
        years = duration_months // 12 if duration_months else None
        if years == 2:
            logger.warning(f"2-year contract found, no 2-year feed-in rates available, using 3-year as fallback")
            return "fixed_3year"
        elif years and years > 1:
            logger.warning(f"{years}-year contract found, using closest available fixed rate")
            return f"fixed_{years}year"
        else:
            logger.warning(f"Unknown fixed duration {duration_months}, using 'fixed_1year' as fallback")
            return "fixed_1year"


def lookup_feedin_tariff(
    provider_id: str,
    contract_type: str,
    duration_months: Optional[int],
) -> Tuple[Optional[str], Optional[float], Optional[float]]:
    """
    Look up feed-in tariff information for a contract.
    
    Returns calculation method, annual cost estimate (for 3000 kWh), and per-kWh rate (if available).
    
    Args:
        provider_id: Normalized provider ID (e.g., "eneco", "budget_energie")
        contract_type: "fixed" or "variable"
        duration_months: Contract duration in months, or None for variable
    
    Returns:
        Tuple of (calculation_method, annual_cost_estimate_eur, rate_per_kwh):
            - calculation_method: str like "fixed_rate_per_kwh", "tiered_staffels"
            - annual_cost_estimate_eur: float for 3000 kWh baseline, or None if not calculable
            - rate_per_kwh: float for fixed-rate providers, None otherwise
    
    Returns (None, None, None) if provider not found or lookup fails.
    """
    if FEEDIN_METHODS_CACHE is None or FEEDIN_TARIFFS_CACHE is None:
        logger.warning(f"Feed-in tariff cache not initialized, cannot lookup {provider_id}")
        return None, None, None
    
    try:
        # Get provider metadata
        provider_meta = FEEDIN_METHODS_CACHE.get("provider_index", {}).get(provider_id)
        if not provider_meta:
            logger.debug(f"Provider {provider_id} not in feed-in methods index")
            return None, None, None
        
        calc_method = provider_meta.get("calculation_method")
        
        # Get tariff data
        tariff_data = FEEDIN_TARIFFS_CACHE.get("fixed_and_variable_contracts", {}).get(provider_id)
        if not tariff_data:
            logger.debug(f"Provider {provider_id} not in feed-in tariffs data")
            return calc_method, None, None
        
        # Normalize duration for lookup
        duration_key = normalize_duration_for_lookup(contract_type, duration_months)
        
        annual_cost_estimate = None
        rate_per_kwh = None
        baseline_kwh = 3000
        
        # Calculate based on method
        if calc_method == "fixed_rate_per_kwh":
            rates = tariff_data.get("rates_per_kwh", {})
            rate_per_kwh = rates.get(duration_key)
            
            if rate_per_kwh:
                annual_cost_estimate = baseline_kwh * float(rate_per_kwh)
                logger.debug(f"{provider_id} {duration_key}: {rate_per_kwh} EUR/kWh -> {annual_cost_estimate}EUR for 3000kWh")
        
        elif calc_method == "tiered_staffels":
            tiers = tariff_data.get("tiers", [])
            
            # Find tier containing 3000 kWh
            for tier in tiers:
                kwh_min = tier.get("kwh_min", 0)
                kwh_max = tier.get("kwh_max")
                
                if kwh_max is None or (kwh_min <= baseline_kwh <= kwh_max):
                    # Use yearly cost directly
                    annual_cost_estimate = tier.get("cost_per_year_eur")
                    logger.debug(f"{provider_id} {duration_key}: tiered at {baseline_kwh}kWh -> {annual_cost_estimate}EUR")
                    break
        
        elif calc_method == "fixed_fee_plus_variable_rate":
            fixed_fee_monthly = tariff_data.get("fixed_fee_per_month_eur")
            variable_rate = tariff_data.get("variable_rate_per_kwh")
            
            if fixed_fee_monthly and variable_rate:
                annual_cost_estimate = (float(fixed_fee_monthly) * 12) + (baseline_kwh * float(variable_rate))
                logger.debug(f"{provider_id}: fee+variable -> {annual_cost_estimate}EUR for 3000kWh")
        
        elif calc_method == "higher_fixed_rate":
            # For embedded costs, use None (costs incorporated in base fee)
            logger.debug(f"{provider_id}: embedded in fixed rate, annual_cost_estimate = None")
            annual_cost_estimate = None
        
        return calc_method, annual_cost_estimate, rate_per_kwh
    
    except Exception as e:
        logger.warning(f"Error looking up feed-in tariff for {provider_id}: {e}")
        return None, None, None


def normalize_provider_id(provider_name: str) -> str:
    """
    Normalize provider name to lowercase underscore-separated ID.
    
    Examples:
        "AllureNRG" -> "allurenerge"
        "ANWB Energie" -> "anwb_energie"
    """
    return provider_name.lower().replace(" ", "_").replace("&", "and")


def extract_variant(contract_name: str) -> Tuple[str, Optional[str]]:
    """
    Extract trailing variant from contract name.
    
    Two patterns supported:
    
    1. Duration-based variant (Cleanenergy, DELTA, Essent, etc.):
       - Pattern: base_name + duration (1/2/3/4 jaar/maanden vast/variabel/zeker) + variant_suffix
       - Examples:
         "Clean Energy 1 jaar vast Actie" → ("Clean Energy 1 jaar vast", "Actie")
         "Clean Energy Huishoudelijk 1 jaar vast - Welkom Terug" → ("Clean Energy Huishoudelijk 1 jaar vast", "Welkom Terug")
         "DELTA Groene Stroom, vaste leveringsprijs (1 jaar) ACQ" → ("DELTA Groene Stroom, vaste leveringsprijs (1 jaar)", "ACQ")
    
    2. Letter-based variant (Budget Energie, Energiedirect, etc.):
       - Pattern: base_name + space + trailing 1-3 uppercase letters
       - Examples:
         "Groene Stroom en Aardgas 1 Jaar Vast A" → ("Groene Stroom en Aardgas 1 Jaar Vast", "A")
         "Groene Stroom en Aardgas 1 Jaar Vast BAT" → ("Groene Stroom en Aardgas 1 Jaar Vast", "BAT")
    
    Returns:
        Tuple of (base_name, variant):
          - base_name: Contract name without variant
          - variant: Extracted variant, or None if no variant found
    """
    contract_name = contract_name.strip()
    
    # Pattern 1: Duration-based variant
    # Match: (number+ jaar/maanden vast/variabel/zeker) OR (halfjaar/kwartaal + status)
    # Then extract anything after it as variant
    duration_pattern = re.compile(
        r'^(.+?)\s*'                           # base name (greedy, non-greedy)
        r'((?:\d+|halfjaar|kwartaal)\s+(?:jaar|maanden|maand)'  # duration number and unit
        r'(?:\s+(?:vast|variabel|zeker|onbepaald))?)'           # optional status
        r'(?:\s*[-–]?\s*(.+?))?$',                               # optional variant after duration (with optional dash)
        re.IGNORECASE
    )
    
    match = duration_pattern.match(contract_name)
    if match:
        base = match.group(1).strip()
        duration = match.group(2).strip()
        variant = match.group(3)
        
        # Only return if we actually found a variant (non-empty group 3)
        if variant and variant.strip():
            variant = variant.strip().lstrip('-–').strip()  # clean up leading dashes
            return f"{base} {duration}", variant if variant else None
    
    # Pattern 2: Letter-based variant (single or triple uppercase letters at end)
    match = re.match(r'^(.+?)\s+([A-Z]{1,3})$', contract_name)
    if match:
        base = match.group(1).strip()
        variant = match.group(2)
        return base, variant
    
    # No variant found
    return contract_name, None


def contract_name_slug(name: str) -> str:
    """
    Generate a URL-safe slug from contract name.
    
    Transformations:
        1. Convert to lowercase
        2. Replace spaces with underscores
        3. Remove parentheses (both opening and closing)
    
    Examples (AllureNRG contracts):
        "Variabel (met zonnepanelen)" → "variabel_met_zonnepanelen"
        "Vaste Prijs 1 jaar (met zonnepanelen)" → "vaste_prijs_1_jaar_met_zonnepanelen"
    
    Examples (Budget Energie base names):
        "Groene Stroom en Aardgas 1 Jaar Vast" → "groene_stroom_en_aardgas_1_jaar_vast"
        "Groene Stroom en Aardgas 1 Jaar Verlenging" → "groene_stroom_en_aardgas_1_jaar_verlenging"
    """
    return name.lower().replace(" ", "_").replace("(", "").replace(")", "")


def extract_contract_name_base(contract_name: str) -> str:
    """
    Extract base contract name by removing product prefixes and duration suffixes.
    
    Removes:
        1. Product type prefixes: "ZekerheidsGarantie", "ZekerheidsGarantie A", "ZekerheidsGarantie Actie", etc.
        2. Duration suffixes at the end: "1 jaar", "3 jaar", "1 maand", etc.
    
    Examples:
        "ZekerheidsGarantie A Groene Stroom (NL) en Gas 1 jaar" → "Groene Stroom (NL) en Gas"
        "ZekerheidsGarantie Actie Groene Stroom (NL) en Gas 1 jaar" → "Groene Stroom (NL) en Gas"
        "Clean Energy Huishoudelijk 1 jaar vast" → "Clean Energy Huishoudelijk"
        "DELTA Groene Stroom, vaste leveringsprijs (1 jaar)" → "DELTA Groene Stroom, vaste leveringsprijs"
    
    Args:
        contract_name: Full contract name string
    
    Returns:
        Base contract name without product prefix or duration suffix
    """
    if not contract_name or contract_name == 'unknown':
        return contract_name
    
    name = contract_name.strip()
    
    # Remove common product prefixes (ZekerheidsGarantie X, Actie X, etc.)
    # Pattern 1: "ZekerheidsGarantie A" or similar (product brand + variant)
    name = re.sub(r'^ZekerheidsGarantie\s+\w+\s+', '', name, flags=re.IGNORECASE)
    # Pattern 2: "ZekerheidsGarantie" or similar (just product brand)
    name = re.sub(r'^ZekerheidsGarantie\s+', '', name, flags=re.IGNORECASE)
    # Pattern 3: "Actie" or similar
    name = re.sub(r'^Actie\s+', '', name, flags=re.IGNORECASE)
    
    # Remove duration suffixes from the end (both "jaar" and "maand" forms)
    # Patterns: "1 jaar", "3 jaar vast", "1 jaar vast", "halfjaar vast", etc.
    name = re.sub(r'\s+\d+\s+(?:jaar|maand|maanden|halfjaar|kwartaal)(?:\s+(?:vast|variabel|zeker|onbepaald))?\s*$', '', name, flags=re.IGNORECASE)
    # Also handle parenthesized durations: " (1 jaar)", " (3 jaar vast)"
    name = re.sub(r'\s*\(\d+\s+(?:jaar|maand|maanden|halfjaar|kwartaal)(?:\s+(?:vast|variabel|zeker|onbepaald))?\)\s*$', '', name, flags=re.IGNORECASE)
    
    return name.strip()


def parse_dutch_decimal(value_str: str) -> Decimal:
    """
    Parse Dutch-formatted decimal string (comma separator) into Decimal.
    
    Examples:
        "108,9000" -> Decimal("108.9000")
        "1,3167" -> Decimal("1.3167")
    
    Raises:
        ValueError: if the value cannot be parsed.
    """
    if value_str is None or value_str == "":
        raise ValueError("Cannot parse empty or None value")
    
    value_str = str(value_str).strip()
    # Replace comma with dot (Dutch uses comma as decimal separator)
    normalized = value_str.replace(",", ".")
    try:
        return Decimal(normalized)
    except Exception as e:
        raise ValueError(f"Cannot parse '{value_str}' as decimal: {e}")


def parse_dutch_month(month_str: str) -> ParsedMonth:
    """
    Parse Dutch month string like "augustus 2025" into ParsedMonth.
    
    Raises:
        ValueError: if the format is unrecognized.
    """
    parts = month_str.strip().lower().split()
    if len(parts) != 2:
        raise ValueError(f"Expected 'month year' format, got '{month_str}'")
    
    month_name, year_str = parts
    
    if month_name not in DUTCH_MONTHS:
        raise ValueError(f"Unknown Dutch month name: '{month_name}'")
    
    try:
        year = int(year_str)
    except ValueError:
        raise ValueError(f"Cannot parse year '{year_str}' as integer")
    
    return ParsedMonth(year=year, month=DUTCH_MONTHS[month_name])


def infer_snapshot_month(
    raw_record: Dict[str, Any],
    filepath: Path
) -> ParsedMonth:
    """
    Infer snapshot month from raw record or filename.
    
    Priority:
    1. _month_idx field in record
    2. Extract from filename (e.g., "contracts_augustus 2025.json")
    
    Raises:
        ValueError: if month cannot be inferred from either source.
    """
    # Try _month_idx field first
    if "_month_idx" in raw_record and raw_record["_month_idx"]:
        try:
            return parse_dutch_month(raw_record["_month_idx"])
        except ValueError as e:
            logger.warning(f"Could not parse _month_idx '{raw_record['_month_idx']}': {e}")
    
    # Try to extract from filename
    filename_stem = filepath.stem  # e.g., "contracts_augustus 2025"
    # Look for pattern like "august 2025" in filename
    for dutch_month in DUTCH_MONTHS.keys():
        if dutch_month in filename_stem.lower():
            # Extract year after the month name
            after_month = filename_stem.lower().split(dutch_month)[1].strip()
            # Find a 4-digit year
            year_parts = [s for s in after_month.split() if s.isdigit() and len(s) == 4]
            if year_parts:
                try:
                    year = int(year_parts[0])
                    return ParsedMonth(year=year, month=DUTCH_MONTHS[dutch_month])
                except (ValueError, IndexError):
                    pass
    
    raise ValueError(
        f"Could not infer snapshot month from record or filename '{filepath.name}'. "
        f"_month_idx={raw_record.get('_month_idx', 'missing')}"
    )


def classify_contract_type(contract_duration: str) -> str:
    """
    Classify contract as 'fixed' or 'variable' based on duration label.
    
    Rules:
    - Contains "Variabel" or "onbepaald" -> "variable"
    - Contains "Vast" -> "fixed"
    
    Raises:
        ValueError: if classification is ambiguous or fails.
    """
    duration_lower = contract_duration.lower()
    
    if "variabel" in duration_lower or "onbepaald" in duration_lower:
        return "variable"
    elif "vast" in duration_lower:
        return "fixed"
    else:
        raise ValueError(
            f"Cannot classify contract type from duration '{contract_duration}'. "
            f"Expected 'Vast' or 'Variabel'."
        )


def parse_duration_months(contract_duration: str) -> Optional[int]:
    """
    Extract duration in months from contract duration label.
    
    Examples:
        "Vast (3 jaar)" -> 36
        "Variabel (onbepaald)" -> None
        "Fixed (2 years)" -> 24 (assumed English fallback)
    
    Returns None if duration is indefinite or cannot be parsed.
    """
    import re
    
    duration_lower = contract_duration.lower()
    
    # If indefinite/onbepaald, return None
    if "onbepaald" in duration_lower:
        return None
    
    # Look for pattern like "3 jaar" or "2 year"
    match = re.search(r'(\d+)\s*(jaar|year|years)', duration_lower)
    if match:
        years = int(match.group(1))
        return years * 12
    
    logger.warning(f"Could not parse duration from '{contract_duration}'")
    return None


def generate_contract_key(
    provider_id: str,
    contract_type: str,
    meter_type: str,
    contract_name_slug: str,
    variant: Optional[str],
    snapshot_month: str,
) -> str:
    """
    Generate a stable, unique contract key.
    
    Format: provider_id | contract_type | meter_type | contract_name_slug | variant | snapshot_month
    
    If variant is None, uses empty string (preserves field count for consistency).
    
    Examples:
        "anwb_energie|fixed|double|modelcontract||2025-08"           (no variant)
        "budget_energie|fixed|double|groene_stroom_1_jaar_vast|A|2025-08"  (variant A)
        "budget_energie|fixed|double|groene_stroom_1_jaar_vast|BAT|2025-08"  (variant BAT)
    """
    variant_str = variant if variant else ""
    parts = [provider_id, contract_type, meter_type, contract_name_slug, variant_str, snapshot_month]
    key = "|".join(parts)
    return key


# ============================================================================
# PARSING & TRANSFORMATION
# ============================================================================

def parse_json_file(filepath: Path) -> List[Dict[str, Any]]:
    """
    Parse a JSON contract file.
    
    Raises:
        json.JSONDecodeError: if file is invalid JSON.
        FileNotFoundError: if file does not exist.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON list, got {type(data).__name__} in {filepath}")
    
    return data


def transform_contract(
    raw_record: Dict[str, Any],
    filepath: Path,
) -> TransformationResult:
    """
    Transform a single raw contract record into normalized rows across tables.
    
    Args:
        raw_record: Raw contract object from JSON
        filepath: Source file path (for logging and meta column)
    
    Returns:
        TransformationResult with contracts, usage, fee, and feedin tier rows.
    
    Raises:
        ValueError: if critical fields are missing or unparseable.
    """
    # ========== Extract and validate required fields ==========
    provider_name = raw_record.get("provider", "").strip()
    if not provider_name:
        raise ValueError("Missing 'provider' field")
    
    contract_name = raw_record.get("contract_name", "").strip()
    if not contract_name:
        raise ValueError("Missing 'contract_name' field")
    
    contract_duration = raw_record.get("contract_duration", "").strip()
    if not contract_duration:
        raise ValueError("Missing 'contract_duration' field")
    
    meter_type = raw_record.get("meter_type", "").strip().lower()
    if meter_type not in ("single", "double"):
        raise ValueError(f"Invalid meter_type '{meter_type}', expected 'single' or 'double'")
    
    tariffs = raw_record.get("tariffs", {})
    if not isinstance(tariffs, dict):
        raise ValueError(f"Expected tariffs to be a dict, got {type(tariffs).__name__}")
    
    source_tuple_id = raw_record.get("_tupleId", "unknown")
    source_session_id = raw_record.get("_session_id", "unknown")
    
    # ========== Infer and normalize metadata ==========
    snapshot_month = infer_snapshot_month(raw_record, filepath)
    contract_type = classify_contract_type(contract_duration)
    duration_months = parse_duration_months(contract_duration)
    provider_id = normalize_provider_id(provider_name)
    
    # ========== Check for commodities ==========
    has_gas = "gas" in tariffs and isinstance(tariffs.get("gas"), dict)
    has_electricity = "electricity" in tariffs and isinstance(tariffs.get("electricity"), dict)
    
    if not (has_gas or has_electricity):
        raise ValueError("Contract has neither gas nor electricity tariffs")
    
    # ========== Extract contract variant and base name ==========
    contract_name_base, variant = extract_variant(contract_name)
    contract_name_simple = extract_contract_name_base(contract_name_base)  # Further simplify (remove duration suffix)
    contract_slug = contract_name_slug(contract_name_simple)
    
    # ========== Generate stable contract key ==========
    contract_key = generate_contract_key(
        provider_id=provider_id,
        contract_type=contract_type,
        meter_type=meter_type,
        contract_name_slug=contract_slug,
        variant=variant,
        snapshot_month=snapshot_month.yyyy_mm,
    )
    
    # ========== Check for feed-in tariff data ==========
    # First check in-file data (for backward compatibility with scraped data)
    has_feed_in_tariff = False
    has_feedin_tiers = False
    feed_in_calculation_method = None
    feed_in_rate_per_kwh = None
    
    if has_electricity:
        elec_tariffs = tariffs.get("electricity", {})
        # Check for any feed-in related field in scraped data
        if elec_tariffs.get("feedin_per_kwh") or elec_tariffs.get("feedin_staffels"):
            has_feed_in_tariff = True
            
            if elec_tariffs.get("feedin_staffels"):
                has_feedin_tiers = True
                feed_in_calculation_method = "tiered_staffels"
            elif elec_tariffs.get("feedin_per_kwh"):
                try:
                    rate = parse_dutch_decimal(elec_tariffs["feedin_per_kwh"])
                    feed_in_rate_per_kwh = float(rate)
                    feed_in_calculation_method = "fixed_rate_per_kwh"
                except (ValueError, TypeError):
                    logger.warning(f"Could not parse feedin_per_kwh for contract {contract_key}")
    
    # Try to look up feed-in tariff from external database if not in scraped data
    if not has_feed_in_tariff:
        try:
            # Normalize provider and get feed-in provider key
            feedin_provider_key = normalize_provider_name(provider_name)
            if feedin_provider_key:
                # Normalize contract type for feed-in lookup
                feedin_contract_type = normalize_contract_duration(contract_duration, feedin_provider_key)
                if feedin_contract_type:
                    has_feed_in_tariff = True
                    # Determine if tiered or fixed rate
                    if "tiered" in feedin_contract_type or feedin_contract_type == "tiered_staffels":
                        has_feedin_tiers = True
                        feed_in_calculation_method = "tiered_staffels"
                    else:
                        feed_in_calculation_method = "fixed_rate_per_kwh"
                        # Try to get the rate (would need to calculate from lookup)
                        logger.debug(f"Feed-in tariff for {provider_name} ({feedin_contract_type}): external DB has data")
        except Exception as e:
            logger.debug(f"Error checking external feed-in DB for {provider_name}: {e}")
    
    # Create contracts row
    # Note: contract_name uses the clean base name (without variant) for uniform frontend display
    contract_row = ContractRow(
        contract_key=contract_key,
        provider_id=provider_id,
        provider_name=provider_name,
        contract_name=contract_name_base,  # Base name without variant for uniform display
        contract_name_base=contract_name_simple,  # Further simplified (product prefix and duration removed)
        contract_name_slug=contract_slug,  # URL-safe slug for deduplication
        variant=variant,  # Extracted variant (A, B, BAT, etc.) or None
        contract_type=contract_type,
        contract_duration_label=contract_duration,
        duration_months=duration_months,
        meter_type=meter_type,
        has_gas=has_gas,
        has_feed_in_tariff=has_feed_in_tariff,
        has_feedin_tiers=has_feedin_tiers,
        feed_in_calculation_method=feed_in_calculation_method,
        feed_in_rate_per_kwh=Decimal(str(feed_in_rate_per_kwh)) if feed_in_rate_per_kwh else None,
        snapshot_month=snapshot_month.yyyy_mm,
        source_file=filepath.name,
        source_session_id=source_session_id,
        source_tuple_id=source_tuple_id,
        estimated_annual_costs=raw_record.get("estimated_annual_costs"),
        is_active=True,
    )
    
    usage_rows: List[UsageRow] = []
    fee_rows: List[FeeRow] = []
    feedin_tier_rows: List[FeedinTierRow] = []
    
    # ========== Process electricity tariffs ==========
    if has_electricity:
        elec_tariffs = tariffs["electricity"]
        
        # Fixed component (fee)
        fixed_yearly = elec_tariffs.get("fixed_yearly")
        if fixed_yearly is not None and fixed_yearly != "":
            try:
                rate = parse_dutch_decimal(fixed_yearly)
                fee_rows.append(FeeRow(
                    contract_key=contract_key,
                    provider_id=provider_id,
                    snapshot_month=snapshot_month.yyyy_mm,
                    fee_component="electricity_supplier_fee",
                    amount=rate,
                    billing_frequency="yearly" if contract_type == "variable" else None,
                    annual_amount=rate,
                    unit="EUR",
                ))
            except ValueError as e:
                logger.warning(f"Could not parse electricity fixed_yearly '{fixed_yearly}': {e}")
        
        # Variable components (usage tariffs)
        if meter_type == "single":
            # Single meter: use piek_per_kwh as the single tariff
            piek = elec_tariffs.get("piek_per_kwh")
            if piek is not None and piek != "":
                try:
                    rate = parse_dutch_decimal(piek)
                    period = snapshot_month.yyyy_mm if contract_type == "variable" else "year"
                    usage_rows.append(UsageRow(
                        contract_key=contract_key,
                        provider_id=provider_id,
                        snapshot_month=snapshot_month.yyyy_mm,
                        commodity="electricity",
                        direction="import",
                        tariff_band="single",
                        period=period,
                        rate=rate,
                        unit="kWh",
                    ))
                except ValueError as e:
                    logger.warning(f"Could not parse electricity piek_per_kwh '{piek}': {e}")
        
        elif meter_type == "double":
            # Double meter: peak and offpeak
            piek = elec_tariffs.get("piek_per_kwh")
            dal = elec_tariffs.get("dal_per_kwh")
            period = snapshot_month.yyyy_mm if contract_type == "variable" else "year"
            
            if piek is not None and piek != "":
                try:
                    rate = parse_dutch_decimal(piek)
                    usage_rows.append(UsageRow(
                        contract_key=contract_key,
                        provider_id=provider_id,
                        snapshot_month=snapshot_month.yyyy_mm,
                        commodity="electricity",
                        direction="import",
                        tariff_band="peak",
                        period=period,
                        rate=rate,
                        unit="kWh",
                    ))
                except ValueError as e:
                    logger.warning(f"Could not parse electricity piek_per_kwh '{piek}': {e}")
            
            if dal is not None and dal != "":
                try:
                    rate = parse_dutch_decimal(dal)
                    usage_rows.append(UsageRow(
                        contract_key=contract_key,
                        provider_id=provider_id,
                        snapshot_month=snapshot_month.yyyy_mm,
                        commodity="electricity",
                        direction="import",
                        tariff_band="offpeak",
                        period=period,
                        rate=rate,
                        unit="kWh",
                    ))
                except ValueError as e:
                    logger.warning(f"Could not parse electricity dal_per_kwh '{dal}': {e}")
    
    # ========== Process gas tariffs ==========
    if has_gas:
        gas_tariffs = tariffs["gas"]
        
        # Fixed component (fee)
        fixed_yearly = gas_tariffs.get("fixed_yearly")
        if fixed_yearly is not None and fixed_yearly != "":
            try:
                rate = parse_dutch_decimal(fixed_yearly)
                fee_rows.append(FeeRow(
                    contract_key=contract_key,
                    provider_id=provider_id,
                    snapshot_month=snapshot_month.yyyy_mm,
                    fee_component="gas_supplier_fee",
                    amount=rate,
                    billing_frequency="yearly" if contract_type == "variable" else None,
                    annual_amount=rate,
                    unit="EUR",
                ))
            except ValueError as e:
                logger.warning(f"Could not parse gas fixed_yearly '{fixed_yearly}': {e}")
        
        # Variable component (usage tariff)
        variable_per_m3 = gas_tariffs.get("variable_per_m3")
        if variable_per_m3 is not None and variable_per_m3 != "":
            try:
                rate = parse_dutch_decimal(variable_per_m3)
                period = snapshot_month.yyyy_mm if contract_type == "variable" else "year"
                usage_rows.append(UsageRow(
                    contract_key=contract_key,
                    provider_id=provider_id,
                    snapshot_month=snapshot_month.yyyy_mm,
                    commodity="gas",
                    direction="import",
                    tariff_band="single",
                    period=period,
                    rate=rate,
                    unit="m3",
                ))
            except ValueError as e:
                logger.warning(f"Could not parse gas variable_per_m3 '{variable_per_m3}': {e}")
    
    # ========== Process feed-in tiers if present ==========
    if has_feedin_tiers and has_electricity:
        elec_tariffs = tariffs.get("electricity", {})
        feedin_staffels = elec_tariffs.get("feedin_staffels")
        
        if isinstance(feedin_staffels, list):
            for idx, tier in enumerate(feedin_staffels):
                try:
                    if isinstance(tier, dict):
                        min_kwh = tier.get("min_kwh")
                        max_kwh = tier.get("max_kwh")
                        rate_str = tier.get("rate")
                        basis_type = tier.get("basis_type", "net_production")  # Default to net
                        
                        if rate_str:
                            rate = parse_dutch_decimal(rate_str)
                            feedin_tier_rows.append(FeedinTierRow(
                                contract_key=contract_key,
                                provider_id=provider_id,
                                snapshot_month=snapshot_month.yyyy_mm,
                                settlement_period="year",  # Feed-in typically settled yearly
                                basis_type=basis_type,
                                tier_index=idx,
                                tier_min_kwh=Decimal(str(min_kwh)) if min_kwh is not None else None,
                                tier_max_kwh=Decimal(str(max_kwh)) if max_kwh is not None else None,
                                tier_amount=rate,
                                unit="EUR/kWh",
                                vat_included=tier.get("vat_included", False),
                            ))
                except (ValueError, KeyError, TypeError) as e:
                    logger.warning(f"Could not parse feed-in tier {idx} for contract {contract_key}: {e}")
    
    return TransformationResult(
        contract_row=contract_row,
        usage_rows=usage_rows,
        fee_rows=fee_rows,
        feedin_tier_rows=feedin_tier_rows,
    )


# ============================================================================
# PARQUET I/O WITH DEDUPLICATION
# ============================================================================

def ensure_schema(table: pa.Table, expected_schema: pa.Schema) -> pa.Table:
    """
    Ensure table conforms to expected schema, adding missing columns if needed.
    
    Useful for handling optional read operations or schema evolution.
    """
    existing_cols = {field.name for field in table.schema}
    
    for field in expected_schema:
        if field.name not in existing_cols:
            # Add missing column with null values
            null_array = pa.nulls(len(table), field.type)
            table = table.append_column(field.name, null_array)
    
    # Reorder to match expected schema
    return table.select([field.name for field in expected_schema])


def dataclass_to_dict(obj: Any) -> Dict[str, Any]:
    """Convert dataclass instance to dict, handling Decimal serialization."""
    result = asdict(obj)
    for key, value in result.items():
        if isinstance(value, Decimal):
            result[key] = float(value)
    return result


def write_or_merge_parquet(
    output_path: Path,
    new_rows: List[Any],
    dataclass_type: type,
    schema: pa.Schema,
    dedup_keys: List[str],
) -> int:
    """
    Write new rows to parquet, merging with existing file and deduplicating.
    
    Args:
        output_path: Path to parquet file
        new_rows: List of dataclass instances to write
        dataclass_type: Type of the dataclass (for schema generation)
        schema: PyArrow schema for the table
        dedup_keys: Column names to use as deduplication key
    
    Returns:
        Number of rows written (after deduplication).
    """
    if not new_rows:
        logger.info(f"No new rows for {output_path.name}, skipping write")
        return 0
    
    # Convert dataclasses to records
    new_records = [dataclass_to_dict(row) for row in new_rows]
    new_df = pd.DataFrame(new_records)
    
    # Ensure all columns are present (in case of empty new data)
    for field in schema:
        if field.name not in new_df.columns:
            new_df[field.name] = None
    
    # Load existing data if file exists
    if output_path.exists():
        logger.debug(f"Loading existing {output_path.name}")
        existing_table = pq.read_table(output_path)
        existing_df = existing_table.to_pandas()
        
        # Concatenate
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        logger.info(f"Combined {len(existing_df)} existing + {len(new_df)} new rows")
    else:
        combined_df = new_df
        logger.info(f"Creating new {output_path.name} with {len(new_df)} rows")
    
    # Deduplicate by keys
    before_dedup = len(combined_df)
    combined_df = combined_df.drop_duplicates(subset=dedup_keys, keep="last")
    after_dedup = len(combined_df)
    
    if before_dedup > after_dedup:
        logger.info(
            f"Deduplicated {output_path.name}: "
            f"{before_dedup} rows -> {after_dedup} rows "
            f"({before_dedup - after_dedup} duplicates removed)"
        )
    
    # Reorder columns to match schema
    col_order = [field.name for field in schema]
    combined_df = combined_df[col_order]
    
    # Convert Decimal to float for numeric fields (needed for PyArrow decimal128 conversion)
    # This handles: rate, amount, annual_amount, tier_min_kwh, tier_max_kwh, tier_amount, feed_in_rate_per_kwh
    decimal_columns = ["rate", "amount", "annual_amount", "tier_min_kwh", "tier_max_kwh", "tier_amount", "feed_in_rate_per_kwh"]
    for col in decimal_columns:
        if col in combined_df.columns:
            combined_df[col] = combined_df[col].apply(
                lambda x: float(x) if isinstance(x, Decimal) else x
            )
    
    # Convert to PyArrow table and write
    table = pa.Table.from_pandas(combined_df, schema=schema)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, output_path)
    logger.info(f"Wrote {after_dedup} rows to {output_path}")
    
    return after_dedup


# ============================================================================
# SCHEMA DEFINITIONS
# ============================================================================

def get_contracts_schema() -> pa.Schema:
    return pa.schema([
        pa.field("contract_key", pa.string()),
        pa.field("provider_id", pa.string()),
        pa.field("provider_name", pa.string()),
        pa.field("contract_name", pa.string()),  # Base name without variant
        pa.field("variant", pa.string(), nullable=True),  # Extracted variant (A, B, BAT, etc.) or None
        pa.field("contract_name_slug", pa.string()),  # URL-safe slug for deduplication
        pa.field("contract_type", pa.string()),  # "fixed" or "variable"
        pa.field("contract_duration_label", pa.string()),
        pa.field("duration_months", pa.int32(), nullable=True),
        pa.field("meter_type", pa.string()),
        pa.field("has_gas", pa.bool_()),
        pa.field("has_feed_in_tariff", pa.bool_()),
        pa.field("has_feedin_tiers", pa.bool_()),
        pa.field("feed_in_calculation_method", pa.string(), nullable=True),  # fixed_rate_per_kwh, tiered_staffels, etc.
        pa.field("feed_in_rate_per_kwh", pa.float64(), nullable=True),  # Changed from decimal128(10, 6) to float64
        pa.field("snapshot_month", pa.string()),  # "YYYY-MM"
        pa.field("source_file", pa.string()),
        pa.field("source_session_id", pa.string()),
        pa.field("source_tuple_id", pa.string()),
        pa.field("estimated_annual_costs", pa.string(), nullable=True),
        pa.field("is_active", pa.bool_()),
    ])


def get_usage_schema() -> pa.Schema:
    return pa.schema([
        pa.field("contract_key", pa.string()),
        pa.field("provider_id", pa.string()),
        pa.field("snapshot_month", pa.string()),
        pa.field("commodity", pa.string()),  # "electricity" or "gas"
        pa.field("direction", pa.string()),  # "import" or "feed_in"
        pa.field("tariff_band", pa.string()),  # "single", "peak", "offpeak"
        pa.field("period", pa.string()),  # "year" or "YYYY-MM"
        pa.field("rate", pa.float64()),  # Changed from decimal128 to float64 for compatibility
        pa.field("unit", pa.string()),  # "kWh" or "m3"
    ])


def get_fees_schema() -> pa.Schema:
    return pa.schema([
        pa.field("contract_key", pa.string()),
        pa.field("provider_id", pa.string()),
        pa.field("snapshot_month", pa.string()),
        pa.field("fee_component", pa.string()),
        pa.field("amount", pa.float64()),  # Changed from decimal128 to float64
        pa.field("billing_frequency", pa.string(), nullable=True),
        pa.field("annual_amount", pa.float64(), nullable=True),  # Changed from decimal128 to float64
        pa.field("unit", pa.string()),
    ])


def get_feedin_tiers_schema() -> pa.Schema:
    return pa.schema([
        pa.field("contract_key", pa.string()),
        pa.field("provider_id", pa.string()),
        pa.field("snapshot_month", pa.string()),
        pa.field("settlement_period", pa.string()),
        pa.field("basis_type", pa.string()),
        pa.field("tier_index", pa.int32()),
        pa.field("tier_min_kwh", pa.float64(), nullable=True),  # Changed from decimal128 to float64
        pa.field("tier_max_kwh", pa.float64(), nullable=True),  # Changed from decimal128 to float64
        pa.field("tier_amount", pa.float64()),  # Changed from decimal128 to float64
        pa.field("unit", pa.string()),
        pa.field("vat_included", pa.bool_()),
    ])


# ============================================================================
# MAIN INGESTION PIPELINE
# ============================================================================

def scan_input_files(input_root: Path) -> List[Path]:
    """
    Recursively scan input directory for contract JSON files.
    
    Looks for files matching pattern: contracts_*.json
    """
    files = []
    for json_file in input_root.rglob("contracts_*.json"):
        files.append(json_file)
    
    logger.info(f"Found {len(files)} contract JSON files in {input_root}")
    return sorted(files)


def ingest_all_contracts(
    input_root: Path,
    output_root: Path,
) -> Dict[str, int]:
    """
    Main ingestion pipeline: read all JSON files, transform, write parquet.
    
    Args:
        input_root: Root directory containing 2025/, 2026/ etc.
        output_root: Directory where tariffs_curated/ will be created
    
    Returns:
        Dict with statistics (num processed, num skipped, num written, etc.)
    """
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    
    # Collect all input files
    json_files = scan_input_files(input_root)
    if not json_files:
        logger.warning(f"No contract JSON files found in {input_root}")
        return {"processed": 0, "skipped": 0, "errors": 0}
    
    # Initialize accumulators
    fixed_contracts: List[ContractRow] = []
    fixed_usage: List[UsageRow] = []
    fixed_fees: List[FeeRow] = []
    fixed_feedin_tiers: List[FeedinTierRow] = []
    
    variable_contracts: List[ContractRow] = []
    variable_usage: List[UsageRow] = []
    variable_fees: List[FeeRow] = []
    variable_feedin_tiers: List[FeedinTierRow] = []
    
    stats = {
        "processed": 0,
        "skipped": 0,
        "errors": 0,
    }
    
    # Process each JSON file
    for json_file in json_files:
        logger.info(f"Processing {json_file.relative_to(input_root)}")
        
        try:
            raw_records = parse_json_file(json_file)
        except Exception as e:
            logger.error(f"Failed to parse JSON file {json_file}: {e}")
            stats["errors"] += 1
            continue
        
        # Process each contract in the file
        for record_idx, raw_record in enumerate(raw_records):
            try:
                result = transform_contract(raw_record, json_file)
                stats["processed"] += 1
                
                # Accumulate by contract type
                if result.contract_row.contract_type == "fixed":
                    fixed_contracts.append(result.contract_row)
                    fixed_usage.extend(result.usage_rows)
                    fixed_fees.extend(result.fee_rows)
                    fixed_feedin_tiers.extend(result.feedin_tier_rows)
                else:  # variable
                    variable_contracts.append(result.contract_row)
                    variable_usage.extend(result.usage_rows)
                    variable_fees.extend(result.fee_rows)
                    variable_feedin_tiers.extend(result.feedin_tier_rows)
            
            except ValueError as e:
                logger.warning(
                    f"Skipped record {record_idx} in {json_file.name}: {e}"
                )
                stats["skipped"] += 1
            except Exception as e:
                logger.error(
                    f"Unexpected error processing record {record_idx} "
                    f"in {json_file.name}: {e}",
                    exc_info=True
                )
                stats["errors"] += 1
    
    # Write parquet files
    logger.info("=" * 70)
    logger.info("Writing parquet files...")
    logger.info("=" * 70)
    
    # Fixed contracts
    # Unique per row: provider_id + contract_type + meter_type + contract_name + variant + snapshot_month
    count = write_or_merge_parquet(
        output_root / "contracts_fixed.parquet",
        fixed_contracts,
        ContractRow,
        get_contracts_schema(),
        dedup_keys=["provider_id", "contract_type", "meter_type", "contract_name", "variant", "snapshot_month"],
    )
    stats["fixed_contracts"] = count
    
    # Variable contracts
    # Unique per row: provider_id + contract_type + meter_type + contract_name + variant + snapshot_month
    count = write_or_merge_parquet(
        output_root / "contracts_variable.parquet",
        variable_contracts,
        ContractRow,
        get_contracts_schema(),
        dedup_keys=["provider_id", "contract_type", "meter_type", "contract_name", "variant", "snapshot_month"],
    )
    stats["variable_contracts"] = count
    
    # Fixed usage
    count = write_or_merge_parquet(
        output_root / "fixed_usage.parquet",
        fixed_usage,
        UsageRow,
        get_usage_schema(),
        dedup_keys=["contract_key", "commodity", "direction", "tariff_band", "period"],
    )
    stats["fixed_usage"] = count
    
    # Variable usage
    count = write_or_merge_parquet(
        output_root / "variable_usage.parquet",
        variable_usage,
        UsageRow,
        get_usage_schema(),
        dedup_keys=["contract_key", "commodity", "direction", "tariff_band", "period"],
    )
    stats["variable_usage"] = count
    
    # Fixed fees
    count = write_or_merge_parquet(
        output_root / "fixed_fees.parquet",
        fixed_fees,
        FeeRow,
        get_fees_schema(),
        dedup_keys=["contract_key", "fee_component"],
    )
    stats["fixed_fees"] = count
    
    # Variable fees
    count = write_or_merge_parquet(
        output_root / "variable_fees.parquet",
        variable_fees,
        FeeRow,
        get_fees_schema(),
        dedup_keys=["contract_key", "fee_component"],
    )
    stats["variable_fees"] = count
    
    # Fixed feedin tiers (even if empty)
    count = write_or_merge_parquet(
        output_root / "fixed_feedin_tiers.parquet",
        fixed_feedin_tiers,
        FeedinTierRow,
        get_feedin_tiers_schema(),
        dedup_keys=["contract_key", "tier_index", "settlement_period"],
    )
    stats["fixed_feedin_tiers"] = count
    
    # Variable feedin tiers (even if empty)
    count = write_or_merge_parquet(
        output_root / "variable_feedin_tiers.parquet",
        variable_feedin_tiers,
        FeedinTierRow,
        get_feedin_tiers_schema(),
        dedup_keys=["contract_key", "tier_index", "settlement_period"],
    )
    stats["variable_feedin_tiers"] = count
    
    return stats


def print_summary(stats: Dict[str, int]) -> None:
    """Print a summary of ingestion statistics."""
    logger.info("=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Records processed:  {stats.get('processed', 0)}")
    logger.info(f"Records skipped:    {stats.get('skipped', 0)}")
    logger.info(f"Parsing errors:     {stats.get('errors', 0)}")
    logger.info("")
    logger.info("Parquet files written:")
    logger.info(f"  contracts_fixed.parquet:      {stats.get('fixed_contracts', 0)} rows")
    logger.info(f"  contracts_variable.parquet:   {stats.get('variable_contracts', 0)} rows")
    logger.info(f"  fixed_usage.parquet:          {stats.get('fixed_usage', 0)} rows")
    logger.info(f"  variable_usage.parquet:       {stats.get('variable_usage', 0)} rows")
    logger.info(f"  fixed_fees.parquet:           {stats.get('fixed_fees', 0)} rows")
    logger.info(f"  variable_fees.parquet:        {stats.get('variable_fees', 0)} rows")
    logger.info(f"  fixed_feedin_tiers.parquet:   {stats.get('fixed_feedin_tiers', 0)} rows")
    logger.info(f"  variable_feedin_tiers.parquet: {stats.get('variable_feedin_tiers', 0)} rows")


# ============================================================================
# CLI ENTRY POINT
# ============================================================================

def main() -> int:
    """
    Command-line interface for tariff ingestion.
    
    Usage:
        python ingest_tariffs.py --input-root ./raw_contracts --output-root ./tariffs_curated
    """
    parser = argparse.ArgumentParser(
        description="Ingest Dutch energy contract tariff data into normalized parquet files."
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        required=True,
        help="Root directory containing year folders (2025/, 2026/, etc.)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="Output directory for tariffs_curated/ parquet files",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(level=log_level)
    
    logger.info("=" * 70)
    logger.info("Dutch Energy Tariff Ingestion Pipeline")
    logger.info("=" * 70)
    logger.info(f"Input root:  {args.input_root.absolute()}")
    logger.info(f"Output root: {args.output_root.absolute()}")
    logger.info("")
    
    # Load feed-in tariff data at startup
    logger.info("Loading feed-in tariff database...")
    try:
        load_feed_in_tariffs()
        logger.info("✓ Feed-in tariff database loaded")
    except Exception as e:
        logger.warning(f"Could not load feed-in tariff database: {e}")
        logger.warning("  Continuing without external feed-in data (in-file data only)")
    
    logger.info("")
    
    # Validate input directory
    if not args.input_root.exists():
        logger.error(f"Input directory does not exist: {args.input_root}")
        return 1
    
    try:
        stats = ingest_all_contracts(args.input_root, args.output_root)
        print_summary(stats)
        logger.info("=" * 70)
        logger.info("Ingestion complete!")
        return 0
    except Exception as e:
        logger.error(f"Fatal error during ingestion: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
