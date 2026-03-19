#!/usr/bin/env python3
"""Test feed-in tariff extraction logic."""

import sys
import logging
from pathlib import Path
from decimal import Decimal

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from ingest_tariffs import (
    transform_contract,
    ContractRow,
    UsageRow,
    FeeRow,
    FeedinTierRow,
)

def test_feedin_fixed_rate():
    """Test extraction of a simple fixed feed-in rate."""
    logger.info("=" * 70)
    logger.info("Test 1: Fixed Feed-in Rate Extraction")
    logger.info("=" * 70)
    
    raw_record = {
        "provider": "Test Provider",
        "contract_name": "Solar Feed-in Plan",
        "contract_duration": "Variabel",  # Dutch term for variable
        "meter_type": "single",
        "_month_idx": "januari 2024",  # Dutch month name
        "tariffs": {
            "electricity": {
                "fixed_yearly": "0.00",
                "piek_per_kwh": "0.25",
                "feedin_per_kwh": "0.15",  # 15 cents per kWh feed-in
            }
        },
    }
    
    try:
        result = transform_contract(raw_record, Path("test.json"))
        
        contract = result.contract_row
        logger.info(f"✓ Contract extracted: {contract.contract_name}")
        logger.info(f"  - has_feed_in_tariff: {contract.has_feed_in_tariff}")
        logger.info(f"  - feed_in_calculation_method: {contract.feed_in_calculation_method}")
        logger.info(f"  - feed_in_rate_per_kwh: {contract.feed_in_rate_per_kwh}")
        logger.info(f"  - feed_in_annual_cost_estimate_eur: {contract.feed_in_annual_cost_estimate_eur}")
        
        assert contract.has_feed_in_tariff, "Should have feed-in tariff"
        assert contract.feed_in_calculation_method == "fixed_rate_per_kwh"
        assert contract.feed_in_rate_per_kwh == Decimal("0.15")
        assert contract.feed_in_annual_cost_estimate_eur == Decimal("450.00")  # 3000 * 0.15
        
        logger.info("✓ Test 1 PASSED\n")
        return True
    except Exception as e:
        logger.error(f"✗ Test 1 FAILED: {e}\n")
        return False

def test_feedin_tiered():
    """Test extraction of tiered feed-in rates."""
    logger.info("=" * 70)
    logger.info("Test 2: Tiered Feed-in Rates Extraction")
    logger.info("=" * 70)
    
    raw_record = {
        "provider": "Green Energy Co",
        "contract_name": "Premium Solar Tariff A",
        "contract_duration": "Vast",  # Dutch term for fixed
        "meter_type": "double",
        "_month_idx": "januari 2024",  # Dutch month name
        "tariffs": {
            "electricity": {
                "fixed_yearly": "50.00",
                "piek_per_kwh": "0.30",
                "dal_per_kwh": "0.20",
                "feedin_staffels": [
                    {
                        "min_kwh": 0,
                        "max_kwh": 1000,
                        "rate": "0.12",
                        "basis_type": "net_production",
                    },
                    {
                        "min_kwh": 1000,
                        "max_kwh": 3000,
                        "rate": "0.14",
                        "basis_type": "net_production",
                    },
                    {
                        "min_kwh": 3000,
                        "max_kwh": None,
                        "rate": "0.10",
                        "basis_type": "net_production",
                    },
                ],
            }
        },
    }
    
    try:
        result = transform_contract(raw_record, Path("test.json"))
        
        contract = result.contract_row
        logger.info(f"✓ Contract extracted: {contract.contract_name}")
        logger.info(f"  - has_feed_in_tariff: {contract.has_feed_in_tariff}")
        logger.info(f"  - has_feedin_tiers: {contract.has_feedin_tiers}")
        logger.info(f"  - feed_in_calculation_method: {contract.feed_in_calculation_method}")
        
        assert contract.has_feed_in_tariff, "Should have feed-in tariff"
        assert contract.has_feedin_tiers, "Should have tiered feedin"
        assert contract.feed_in_calculation_method == "tiered_staffels"
        
        # Check feedin tier rows
        logger.info(f"\n  Feedin tiers ({len(result.feedin_tier_rows)} rows):")
        for tier in result.feedin_tier_rows:
            logger.info(f"    - Tier {tier.tier_index}: {tier.tier_min_kwh}-{tier.tier_max_kwh} kWh @ {tier.tier_amount} EUR/kWh")
        
        assert len(result.feedin_tier_rows) == 3, "Should have 3 tiers"
        
        # Verify first tier
        tier0 = result.feedin_tier_rows[0]
        assert tier0.tier_index == 0
        assert tier0.tier_min_kwh == Decimal("0")
        assert tier0.tier_max_kwh == Decimal("1000")
        assert tier0.tier_amount == Decimal("0.12")
        assert tier0.basis_type == "net_production"
        
        logger.info("✓ Test 2 PASSED\n")
        return True
    except Exception as e:
        logger.error(f"✗ Test 2 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False

def test_no_feedin():
    """Test contract without feed-in tariff."""
    logger.info("=" * 70)
    logger.info("Test 3: Contract Without Feed-in")
    logger.info("=" * 70)
    
    raw_record = {
        "provider": "Regular Provider",
        "contract_name": "Basic Tariff",
        "contract_duration": "Variabel",  # Dutch term for variable
        "meter_type": "single",
        "_month_idx": "januari 2024",  # Dutch month name
        "tariffs": {
            "electricity": {
                "fixed_yearly": "100.00",
                "piek_per_kwh": "0.28",
            }
        },
    }
    
    try:
        result = transform_contract(raw_record, Path("test.json"))
        
        contract = result.contract_row
        logger.info(f"✓ Contract extracted: {contract.contract_name}")
        logger.info(f"  - has_feed_in_tariff: {contract.has_feed_in_tariff}")
        
        assert not contract.has_feed_in_tariff, "Should not have feed-in tariff"
        assert len(result.feedin_tier_rows) == 0, "Should have no feedin tiers"
        
        logger.info("✓ Test 3 PASSED\n")
        return True
    except Exception as e:
        logger.error(f"✗ Test 3 FAILED: {e}\n")
        return False

def main():
    """Run all tests."""
    logger.info("\n" + "=" * 70)
    logger.info("FEED-IN EXTRACTION TESTS")
    logger.info("=" * 70 + "\n")
    
    results = [
        test_feedin_fixed_rate(),
        test_feedin_tiered(),
        test_no_feedin(),
    ]
    
    logger.info("=" * 70)
    logger.info(f"Results: {sum(results)}/{len(results)} tests passed")
    logger.info("=" * 70)
    
    return all(results)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
