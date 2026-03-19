#!/usr/bin/env python3
"""
Unit tests for tariff ingestion pipeline.

Run with: pytest test_ingest_tariffs.py -v

"""

import pytest
from pathlib import Path
from decimal import Decimal
from tempfile import TemporaryDirectory
import json

# Import functions to test (adjust path as needed)
# from ingest_tariffs import (
#     parse_dutch_decimal,
#     parse_dutch_month,
#     classify_contract_type,
#     parse_duration_months,
#     normalize_provider_id,
#     contract_name_slug,
#     generate_contract_key,
#     ParsedMonth,
# )


class TestDutchDecimalParsing:
    """Test Dutch number format parsing."""
    
    def test_parse_dutch_decimal_basic(self):
        """Parse simple Dutch decimal."""
        from ingest_tariffs import parse_dutch_decimal
        assert parse_dutch_decimal("108,9000") == Decimal("108.9")
    
    def test_parse_dutch_decimal_single_digit(self):
        """Parse single digit after comma."""
        from ingest_tariffs import parse_dutch_decimal
        assert parse_dutch_decimal("1,5") == Decimal("1.5")
    
    def test_parse_dutch_decimal_large_number(self):
        """Parse large number."""
        from ingest_tariffs import parse_dutch_decimal
        assert parse_dutch_decimal("1234,5678") == Decimal("1234.5678")
    
    def test_parse_dutch_decimal_zero_point(self):
        """Parse zero point something."""
        from ingest_tariffs import parse_dutch_decimal
        result = parse_dutch_decimal("0,2862")
        assert result == Decimal("0.2862")
    
    def test_parse_dutch_decimal_invalid_raises(self):
        """Invalid decimal raises ValueError."""
        from ingest_tariffs import parse_dutch_decimal
        with pytest.raises(ValueError):
            parse_dutch_decimal("abc,def")
    
    def test_parse_dutch_decimal_empty_raises(self):
        """Empty string raises ValueError."""
        from ingest_tariffs import parse_dutch_decimal
        with pytest.raises(ValueError):
            parse_dutch_decimal("")


class TestDutchMonthParsing:
    """Test Dutch month parsing."""
    
    def test_parse_august_2025(self):
        """Parse August 2025."""
        from ingest_tariffs import parse_dutch_month
        result = parse_dutch_month("augustus 2025")
        assert result.year == 2025
        assert result.month == 8
        assert result.yyyy_mm == "2025-08"
    
    def test_parse_januari(self):
        """Parse January."""
        from ingest_tariffs import parse_dutch_month
        result = parse_dutch_month("januari 2024")
        assert result.year == 2024
        assert result.month == 1
    
    def test_parse_december(self):
        """Parse December."""
        from ingest_tariffs import parse_dutch_month
        result = parse_dutch_month("december 2025")
        assert result.year == 2025
        assert result.month == 12
    
    def test_parse_invalid_month_raises(self):
        """Invalid month name raises ValueError."""
        from ingest_tariffs import parse_dutch_month
        with pytest.raises(ValueError):
            parse_dutch_month("invalid 2025")
    
    def test_parse_invalid_year_raises(self):
        """Invalid year raises ValueError."""
        from ingest_tariffs import parse_dutch_month
        with pytest.raises(ValueError):
            parse_dutch_month("augustus notayear")


class TestContractClassification:
    """Test contract type classification."""
    
    def test_classify_vast_as_fixed(self):
        """Vast contract classified as fixed."""
        from ingest_tariffs import classify_contract_type
        assert classify_contract_type("Vast (3 jaar)") == "fixed"
    
    def test_classify_variabel_as_variable(self):
        """Variabel contract classified as variable."""
        from ingest_tariffs import classify_contract_type
        assert classify_contract_type("Variabel (onbepaald)") == "variable"
    
    def test_classify_case_insensitive(self):
        """Classification is case-insensitive."""
        from ingest_tariffs import classify_contract_type
        assert classify_contract_type("VAST (2 JAAR)") == "fixed"
        assert classify_contract_type("VARIABEL (ONBEPAALD)") == "variable"
    
    def test_classify_invalid_raises(self):
        """Unknown contract type raises ValueError."""
        from ingest_tariffs import classify_contract_type
        with pytest.raises(ValueError):
            classify_contract_type("Unknown type")


class TestDurationParsing:
    """Test duration parsing."""
    
    def test_parse_3_years(self):
        """Parse 3-year contract."""
        from ingest_tariffs import parse_duration_months
        assert parse_duration_months("Vast (3 jaar)") == 36
    
    def test_parse_1_year(self):
        """Parse 1-year contract."""
        from ingest_tariffs import parse_duration_months
        assert parse_duration_months("Vast (1 jaar)") == 12
    
    def test_parse_indefinite_returns_none(self):
        """Indefinite contract returns None."""
        from ingest_tariffs import parse_duration_months
        assert parse_duration_months("Variabel (onbepaald)") is None
    
    def test_parse_no_duration_returns_none(self):
        """No duration info returns None."""
        from ingest_tariffs import parse_duration_months
        result = parse_duration_months("Some contract")
        assert result is None


class TestProviderNormalization:
    """Test provider ID normalization."""
    
    def test_normalize_allurenerge(self):
        """Normalize AllureNRG."""
        from ingest_tariffs import normalize_provider_id
        assert normalize_provider_id("AllureNRG") == "allurenerge"
    
    def test_normalize_anwb_energie(self):
        """Normalize ANWB Energie."""
        from ingest_tariffs import normalize_provider_id
        assert normalize_provider_id("ANWB Energie") == "anwb_energie"
    
    def test_normalize_spaces_to_underscores(self):
        """Spaces converted to underscores."""
        from ingest_tariffs import normalize_provider_id
        assert normalize_provider_id("Some Provider Inc") == "some_provider_inc"
    
    def test_normalize_ampersand(self):
        """Ampersand converted to 'and'."""
        from ingest_tariffs import normalize_provider_id
        assert normalize_provider_id("A & B Energy") == "a_and_b_energy"


class TestContractNameSlug:
    """Test contract name slug generation."""
    
    def test_slug_basic(self):
        """Generate basic slug."""
        from ingest_tariffs import contract_name_slug
        assert contract_name_slug("Modelcontract") == "modelcontract"
    
    def test_slug_with_spaces(self):
        """Generate slug with spaces."""
        from ingest_tariffs import contract_name_slug
        result = contract_name_slug("Variabele Prijs Standard")
        assert result == "variabele_prijs_standard"
    
    def test_slug_with_parens(self):
        """Parentheses removed from slug."""
        from ingest_tariffs import contract_name_slug
        result = contract_name_slug("Plan (Premium)")
        assert result == "plan_premium"


class TestContractKeyGeneration:
    """Test contract key generation."""
    
    def test_generate_key_anwb(self):
        """Generate key for ANWB contract."""
        from ingest_tariffs import generate_contract_key
        key = generate_contract_key(
            provider_id="anwb_energie",
            contract_type="fixed",
            meter_type="double",
            contract_name="Modelcontract",
            snapshot_month="2025-08",
        )
        assert key == "anwb_energie|fixed|double|modelcontract|2025-08"
    
    def test_generate_key_unique_per_meter_type(self):
        """Keys differ by meter type."""
        from ingest_tariffs import generate_contract_key
        key1 = generate_contract_key(
            provider_id="test",
            contract_type="fixed",
            meter_type="single",
            contract_name="Plan",
            snapshot_month="2025-08",
        )
        key2 = generate_contract_key(
            provider_id="test",
            contract_type="fixed",
            meter_type="double",
            contract_name="Plan",
            snapshot_month="2025-08",
        )
        assert key1 != key2
    
    def test_generate_key_unique_per_month(self):
        """Keys differ by month."""
        from ingest_tariffs import generate_contract_key
        key1 = generate_contract_key(
            provider_id="test",
            contract_type="fixed",
            meter_type="single",
            contract_name="Plan",
            snapshot_month="2025-07",
        )
        key2 = generate_contract_key(
            provider_id="test",
            contract_type="fixed",
            meter_type="single",
            contract_name="Plan",
            snapshot_month="2025-08",
        )
        assert key1 != key2


class TestTransformContract:
    """Test contract transformation."""
    
    def test_transform_variable_single_meter(self):
        """Transform variable single-meter contract."""
        from ingest_tariffs import transform_contract
        from pathlib import Path
        
        raw_record = {
            "provider": "AllureNRG",
            "contract_name": "Variabele Prijs (met zonnepanelen)",
            "contract_duration": "Variabel (onbepaald)",
            "meter_type": "single",
            "tariffs": {
                "gas": {
                    "fixed_yearly": "108,9000",
                    "variable_per_m3": "1,3167"
                },
                "electricity": {
                    "fixed_yearly": "363,0000",
                    "piek_per_kwh": "0,2862",
                    "dal_per_kwh": None
                }
            },
            "estimated_annual_costs": "189",
            "_tupleId": "8",
            "_month_idx": "augustus 2025",
            "_session_id": "SESSION123"
        }
        
        filepath = Path("contracts_augustus 2025.json")
        result = transform_contract(raw_record, filepath)
        
        # Verify contract row
        assert result.contract_row.contract_type == "variable"
        assert result.contract_row.meter_type == "single"
        assert result.contract_row.has_gas is True
        assert result.contract_row.snapshot_month == "2025-08"
        
        # Verify usage rows (2: electricity + gas)
        assert len(result.usage_rows) == 2
        
        # Verify fee rows (2: electricity + gas supplier fees)
        assert len(result.fee_rows) == 2
    
    def test_transform_fixed_double_meter(self):
        """Transform fixed double-meter contract."""
        from ingest_tariffs import transform_contract
        from pathlib import Path
        
        raw_record = {
            "provider": "ANWB Energie",
            "contract_name": "Modelcontract",
            "contract_duration": "Vast (3 jaar)",
            "meter_type": "double",
            "tariffs": {
                "gas": {
                    "fixed_yearly": "186,0012",
                    "variable_per_m3": "6,0955"
                },
                "electricity": {
                    "fixed_yearly": "186,0012",
                    "piek_per_kwh": "1,5770",
                    "dal_per_kwh": "1,2135"
                }
            },
            "estimated_annual_costs": "930",
            "_tupleId": "1",
            "_month_idx": "augustus 2025",
            "_session_id": "SESSION456"
        }
        
        filepath = Path("contracts_augustus 2025.json")
        result = transform_contract(raw_record, filepath)
        
        # Verify contract row
        assert result.contract_row.contract_type == "fixed"
        assert result.contract_row.meter_type == "double"
        assert result.contract_row.duration_months == 36
        assert result.contract_row.snapshot_month == "2025-08"
        
        # Verify usage rows (3: electricity peak, electricity offpeak, gas)
        assert len(result.usage_rows) == 3
        
        # Check tariff bands
        bands = {row.tariff_band for row in result.usage_rows}
        assert "peak" in bands
        assert "offpeak" in bands
        
        # Verify fee rows (2: electricity + gas supplier fees)
        assert len(result.fee_rows) == 2
    
    def test_transform_missing_provider_raises(self):
        """Missing provider raises ValueError."""
        from ingest_tariffs import transform_contract
        from pathlib import Path
        
        raw_record = {
            # "provider": missing!
            "contract_name": "Test",
            "contract_duration": "Vast",
            "meter_type": "single",
            "tariffs": {
                "electricity": {
                    "fixed_yearly": "100,00",
                    "piek_per_kwh": "0,20"
                }
            },
            "_month_idx": "august 2025"
        }
        
        filepath = Path("test.json")
        with pytest.raises(ValueError, match="provider"):
            transform_contract(raw_record, filepath)


class TestIntegrationParquetRoundTrip:
    """Integration test: write and read parquet."""
    
    def test_write_and_read_parquet(self):
        """Write to parquet and read back."""
        from ingest_tariffs import (
            write_or_merge_parquet,
            ContractRow,
            get_contracts_schema,
        )
        
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_contracts.parquet"
            
            # Create sample data
            contract_row = ContractRow(
                contract_key="test|fixed|single|test|2025-08",
                provider_id="test_provider",
                provider_name="Test Provider",
                contract_name="Test Contract",
                contract_type="fixed",
                contract_duration_label="Vast (1 jaar)",
                duration_months=12,
                meter_type="single",
                has_gas=False,
                has_feed_in_tariff=False,
                has_feedin_tiers=False,
                snapshot_month="2025-08",
                source_file="test.json",
                source_session_id="test_session",
                source_tuple_id="test_tuple",
                estimated_annual_costs="100",
                is_active=True,
            )
            
            # Write
            count = write_or_merge_parquet(
                output_path,
                [contract_row],
                ContractRow,
                get_contracts_schema(),
                dedup_keys=["contract_key"],
            )
            
            assert count == 1
            assert output_path.exists()
            
            # Read back
            import pyarrow.parquet as pq
            table = pq.read_table(output_path)
            df = table.to_pandas()
            
            assert len(df) == 1
            assert df.iloc[0]["contract_key"] == "test|fixed|single|test|2025-08"
    
    def test_parquet_deduplication(self):
        """Verify deduplication on rewrite."""
        from ingest_tariffs import (
            write_or_merge_parquet,
            ContractRow,
            get_contracts_schema,
        )
        
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_dedup.parquet"
            
            # Create sample data
            contract_row = ContractRow(
                contract_key="test|fixed|single|test|2025-08",
                provider_id="test",
                provider_name="Test",
                contract_name="Test",
                contract_type="fixed",
                contract_duration_label="Vast",
                duration_months=12,
                meter_type="single",
                has_gas=False,
                has_feed_in_tariff=False,
                has_feedin_tiers=False,
                snapshot_month="2025-08",
                source_file="test.json",
                source_session_id="test",
                source_tuple_id="test",
                estimated_annual_costs="100",
            )
            
            # Write once
            write_or_merge_parquet(
                output_path,
                [contract_row],
                ContractRow,
                get_contracts_schema(),
                dedup_keys=["contract_key"],
            )
            
            # Write same data again
            count = write_or_merge_parquet(
                output_path,
                [contract_row],
                ContractRow,
                get_contracts_schema(),
                dedup_keys=["contract_key"],
            )
            
            # Should still be 1 row (deduplicated)
            assert count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
