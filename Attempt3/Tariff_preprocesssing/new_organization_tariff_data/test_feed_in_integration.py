#!/usr/bin/env python3
"""Integration test for feed-in tariff system."""

import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))

from feed_in_lookup import (
    load_feed_in_tariffs,
    normalize_provider_name,
    normalize_contract_duration,
    get_feed_in_tariff,
    get_provider_info,
)

def test_provider_loading():
    """Test that feed-in data loads correctly."""
    logger.info("=" * 70)
    logger.info("Test 1: Feed-in Data Loading")
    logger.info("=" * 70)
    
    try:
        tariffs = load_feed_in_tariffs()
        assert len(tariffs) > 0, "No tariffs loaded"
        
        expected_providers = ["essent", "energiedirect", "eneco", "oxxio"]
        for provider_key in expected_providers:
            assert provider_key in tariffs, f"Missing provider: {provider_key}"
        
        logger.info(f"✓ Loaded {len(tariffs)} providers")
        for key in sorted(tariffs.keys())[:5]:
            name = tariffs[key].get("provider", key)
            logger.info(f"  - {key}: {name}")
        
        return True
    except AssertionError as e:
        logger.error(f"✗ Test failed: {e}")
        return False

def test_provider_mapping():
    """Test provider name normalization."""
    logger.info("=" * 70)
    logger.info("Test 2: Provider Name Mapping")
    logger.info("=" * 70)
    
    tests = [
        ("Essent", "essent"),
        ("essent", "essent"),
        ("ESSENT", "essent"),
        ("Energiedirect", "energiedirect"),
        ("energie direct", "energiedirect"),
        ("Eneco", "eneco"),
        ("Engie", "engie"),
        ("Unknown Provider", None),
    ]
    
    passed = 0
    for input_name, expected_key in tests:
        result = normalize_provider_name(input_name)
        status = "✓" if result == expected_key else "✗"
        logger.info(f"  {status} '{input_name}' -> {result} (expected: {expected_key})")
        if result == expected_key:
            passed += 1
    
    success = passed == len(tests)
    logger.info(f"\n✓ {passed}/{len(tests)} tests passed" if success else f"\n✗ {passed}/{len(tests)} tests passed")
    return success

def test_duration_mapping():
    """Test contract duration normalization."""
    logger.info("=" * 70)
    logger.info("Test 3: Duration Normalization")
    logger.info("=" * 70)
    
    tests = [
        ("essent", "Vast", "fixed"),
        ("essent", "Variabel", "variable"),
        ("eneco", "Variabel", "variable"),
        ("eneco", "Vast", None),  # Eneco doesn't have "fixed", only "fixed_1year", etc.
    ]
    
    passed = 0
    for provider_key, duration, expected_contains in tests:
        result = normalize_contract_duration(duration, provider_key)
        if expected_contains is None:
            success = result is None or "fixed" in (result or "").lower()
        else:
            success = result is not None and expected_contains in result.lower()
        
        status = "✓" if success else "✗"
        logger.info(f"  {status} {provider_key} + '{duration}' -> {result}")
        if success:
            passed += 1
    
    success = passed == len(tests)
    logger.info(f"\n✓ {passed}/{len(tests)} tests passed" if success else f"\n✗ {passed}/{len(tests)} tests passed")
    return success

def test_tariff_lookups():
    """Test feed-in tariff lookups."""
    logger.info("=" * 70)
    logger.info("Test 4: Feed-in Tariff Lookups")
    logger.info("=" * 70)
    
    tests = [
        ("Essent", "Vast", 3000, 373.80),  # Tiered lookup, should match tier
        ("Energiedirect", "Variabel", 500, 48.84),  # Monthly/yearly in tier
        ("Eneco", "Variabel", 5000, True),  # Should return something (0.142 * 5000 = 710)
    ]
    
    passed = 0
    for provider, duration, kwh, expected in tests:
        try:
            result = get_feed_in_tariff(provider, duration, kwh)
            
            if isinstance(expected, bool):
                success = result is not None
                logger.info(f"  ✓ {provider} @ {kwh} kWh: €{result} (has value)")
            else:
                success = result is not None and abs(float(result) - expected) < 1.0
                logger.info(f"  {'✓' if success else '✗'} {provider} @ {kwh} kWh: €{result:.2f} (expected ~€{expected})")
            
            if success:
                passed += 1
        except Exception as e:
            logger.error(f"  ✗ {provider}: {e}")
    
    success = passed == len(tests)
    logger.info(f"\n✓ {passed}/{len(tests)} tests passed" if success else f"\n✗ {passed}/{len(tests)} tests passed")
    return success

def test_provider_info():
    """Test provider info retrieval."""
    logger.info("=" * 70)
    logger.info("Test 5: Provider Info Retrieval")
    logger.info("=" * 70)
    
    try:
        info = get_provider_info("Essent")
        assert info is not None, "Could not get Essent info"
        
        logger.info(f"✓ Essent info retrieved:")
        logger.info(f"  - Provider: {info.get('provider')}")
        logger.info(f"  - Calculation: {info.get('calculation_method')}")
        logger.info(f"  - Tiers: {len(info.get('tiers', []))}")
        logger.info(f"  - Contract types: {info.get('contract_types')}")
        
        return True
    except AssertionError as e:
        logger.error(f"✗ Test failed: {e}")
        return False

def main():
    """Run all integration tests."""
    logger.info("\n" + "=" * 70)
    logger.info("FEED-IN LOOKUP INTEGRATION TESTS")
    logger.info("=" * 70 + "\n")
    
    results = [
        test_provider_loading(),
        test_provider_mapping(),
        test_duration_mapping(),
        test_tariff_lookups(),
        test_provider_info(),
    ]
    
    logger.info("\n" + "=" * 70)
    logger.info(f"OVERALL: {sum(results)}/{len(results)} test groups passed")
    logger.info("=" * 70)
    
    return all(results)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
