#!/usr/bin/env python3
"""
Feed-in tariff lookup utilities.

Provides functions for:
- Loading and caching feed-in tariff data
- Provider mapping and normalization
- Duration mapping (contract type normalization)
- Feed-in tariff lookups by provider, contract type, and usage
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from decimal import Decimal

logger = logging.getLogger(__name__)

# Global cache for feed-in tariffs
FEEDIN_CACHE: Optional[Dict[str, Any]] = None
PROVIDER_MAPPING_CACHE: Optional[Dict[str, str]] = None


def load_feed_in_tariffs(filepath: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load and cache feed-in tariff data from JSON file.
    
    Args:
        filepath: Path to feed_in_tariffs.json. If None, loads from same directory as this script.
    
    Returns:
        Dictionary of feed-in tariff data by provider key
    
    Raises:
        FileNotFoundError: if file cannot be found
        json.JSONDecodeError: if JSON is invalid
    """
    global FEEDIN_CACHE
    
    if FEEDIN_CACHE is not None:
        return FEEDIN_CACHE
    
    if filepath is None:
        filepath = Path(__file__).parent / "feed_in_tariffs.json"
    
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Feed-in tariffs file not found: {filepath}")
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Extract the fixed_and_variable_contracts section
        FEEDIN_CACHE = data.get("fixed_and_variable_contracts", {})
        logger.info(f"Loaded {len(FEEDIN_CACHE)} providers from feed-in tariffs")
        return FEEDIN_CACHE
    
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in feed-in tariffs file: {e}")
        raise
    except Exception as e:
        logger.error(f"Error loading feed-in tariffs: {e}")
        raise


def build_provider_mapping() -> Dict[str, str]:
    """
    Build a mapping from provider name/alias to canonical provider key.
    
    Used to normalize provider names from contracts to standard keys in feed-in data.
    
    Returns:
        Dictionary mapping normalized names to provider keys
    """
    global PROVIDER_MAPPING_CACHE
    
    if PROVIDER_MAPPING_CACHE is not None:
        return PROVIDER_MAPPING_CACHE
    
    tariffs = load_feed_in_tariffs()
    mapping = {}
    
    for provider_key, provider_data in tariffs.items():
        # Add canonical name
        canonical_name = provider_data.get("provider", provider_key).lower()
        mapping[canonical_name] = provider_key
        
        # Add any aliases
        aliases = provider_data.get("provider_aliases", [])
        for alias in aliases:
            mapping[alias.lower()] = provider_key
    
    PROVIDER_MAPPING_CACHE = mapping
    logger.debug(f"Built provider mapping with {len(mapping)} entries")
    return PROVIDER_MAPPING_CACHE


def normalize_provider_name(provider_name: str) -> Optional[str]:
    """
    Normalize a provider name to the canonical key in feed-in tariffs.
    
    Args:
        provider_name: Raw provider name from contract
    
    Returns:
        Canonical provider key if found, else None
    """
    if not provider_name:
        return None
    
    mapping = build_provider_mapping()
    normalized = provider_name.strip().lower()
    return mapping.get(normalized)


def normalize_contract_duration(contract_duration: str, provider_key: str) -> Optional[str]:
    """
    Map contract duration from ESB format to feed-in tariff format.
    
    Examples:
        "Vast" (fixed) with any provider -> "fixed" or "fixed_1year", etc.
        "Variabel" (variable) with any provider -> "variable"
    
    Args:
        contract_duration: Contract duration label from scraper
        provider_key: Canonical provider key
    
    Returns:
        Normalized duration matching provider's contract_types, or None if no match
    """
    if not contract_duration or not provider_key:
        return None
    
    tariffs = load_feed_in_tariffs()
    provider_data = tariffs.get(provider_key, {})
    contract_types = provider_data.get("contract_types", [])
    
    duration_normalized = contract_duration.strip().lower()
    
    # Map common Dutch terms
    if "vast" in duration_normalized or "fixed" in duration_normalized:
        # Try to find a matching fixed type
        for ctype in contract_types:
            if "fixed" in ctype.lower():
                return ctype
    elif "variabel" in duration_normalized or "variable" in duration_normalized:
        # Try to find variable type
        for ctype in contract_types:
            if "variable" in ctype.lower():
                return ctype
    
    # No match found
    return None


def get_feed_in_tariff(
    provider_name: str,
    contract_duration: str,
    annual_kwh: float,
) -> Optional[Decimal]:
    """
    Lookup feed-in tariff for a specific contract.
    
    Args:
        provider_name: Provider name from contract
        contract_duration: Contract duration from contract
        annual_kwh: Annual kWh production (for tiered lookups)
    
    Returns:
        Annual feed-in tariff in EUR, or None if not found or not applicable
    
    Examples:
        >>> get_feed_in_tariff("Essent", "Vast", 3000)
        Decimal('373.80')  # Annual estimate for 3000 kWh
        
        >>> get_feed_in_tariff("Eneco", "Variabel", 5000)
        Decimal('710.00')  # 0.142 EUR/kWh * 5000 kWh
    """
    provider_key = normalize_provider_name(provider_name)
    if not provider_key:
        logger.debug(f"No feed-in data found for provider: {provider_name}")
        return None
    
    normalized_duration = normalize_contract_duration(contract_duration, provider_key)
    if not normalized_duration:
        logger.debug(f"No matching duration for {provider_name}/{contract_duration}")
        return None
    
    tariffs = load_feed_in_tariffs()
    provider_data = tariffs.get(provider_key, {})
    
    calc_method = provider_data.get("calculation_method")
    
    if calc_method == "fixed_rate_per_kwh":
        # Simple rate-based calculation
        rates = provider_data.get("rates_per_kwh", {})
        rate = rates.get(normalized_duration)
        if rate is not None:
            return Decimal(str(rate * annual_kwh))
    
    elif calc_method == "tiered_staffels":
        # Tiered calculation - find the tier that matches annual_kwh
        tiers = provider_data.get("tiers", [])
        
        # Find the matching tier
        for tier in tiers:
            kwh_min = tier.get("kwh_min", 0)
            kwh_max = tier.get("kwh_max")
            
            # Check if annual_kwh falls in this tier
            if annual_kwh >= kwh_min:
                if kwh_max is None or annual_kwh <= kwh_max:
                    # This is the matching tier
                    # Look for the column that matches normalized_duration
                    
                    # Try exact match first
                    if normalized_duration in tier:
                        return Decimal(str(tier[normalized_duration]))
                    
                    # Try partial match (e.g., "fixed_1year" -> "fixed_1year" column)
                    for key, value in tier.items():
                        if normalized_duration in key or key in normalized_duration:
                            return Decimal(str(value))
                    
                    # Fall back to cost_per_year_eur or annual total
                    if "cost_per_year_eur" in tier:
                        return Decimal(str(tier["cost_per_year_eur"]))
        
        # If no tier matched, use the last tier (highest usage)
        if tiers:
            last_tier = tiers[-1]
            if normalized_duration in last_tier:
                return Decimal(str(last_tier[normalized_duration]))
            elif "cost_per_year_eur" in last_tier:
                return Decimal(str(last_tier["cost_per_year_eur"]))
    
    elif calc_method == "fixed_fee_plus_variable_rate":
        # Combined fixed fee + variable rate (e.g., Engie)
        fixed_fee = provider_data.get("fixed_fee_per_month_eur", 0)
        rate = provider_data.get("variable_rate_per_kwh", 0)
        annual = (fixed_fee * 12) + (rate * annual_kwh)
        return Decimal(str(annual))
    
    logger.debug(f"Could not calculate feed-in tariff for {provider_name}/{contract_duration}")
    return None


def get_provider_info(provider_name: str) -> Optional[Dict[str, Any]]:
    """
    Get full provider info from feed-in database.
    
    Args:
        provider_name: Provider name from contract
    
    Returns:
        Provider data dictionary, or None if not found
    """
    provider_key = normalize_provider_name(provider_name)
    if not provider_key:
        return None
    
    tariffs = load_feed_in_tariffs()
    return tariffs.get(provider_key)


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)
    
    print("Feed-in Lookup Test")
    print("=" * 70)
    
    # Test provider mapping
    print("\nProvider Mapping:")
    print(f"  'Essent' -> {normalize_provider_name('Essent')}")
    print(f"  'essent' -> {normalize_provider_name('essent')}")
    print(f"  'energie direct' -> {normalize_provider_name('energie direct')}")
    
    # Test duration mapping
    print("\nDuration Mapping:")
    print(f"  'Vast' (Essent) -> {normalize_contract_duration('Vast', 'essent')}")
    print(f"  'Variabel' (Essent) -> {normalize_contract_duration('Variabel', 'essent')}")
    
    # Test tariff lookup
    print("\nFeed-in Tariff Lookups:")
    print(f"  Essent @ 3000 kWh: €{get_feed_in_tariff('Essent', 'Vast', 3000)}")
    print(f"  Eneco @ 5000 kWh: €{get_feed_in_tariff('Eneco', 'Variabel', 5000)}")
    print(f"  Energiedirect @ 2000 kWh: €{get_feed_in_tariff('Energiedirect', 'Variabel', 2000)}")
