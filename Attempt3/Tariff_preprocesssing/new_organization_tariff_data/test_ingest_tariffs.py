#!/usr/bin/env python3
"""
Tests for the create-storage-files ingestion pipeline.
"""

from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util
import sys

import pytest


def load_ingest_module():
    script_path = (
        Path(__file__).parent
        / "create storage files"
        / "ingest_tariffs.py"
    )
    spec = importlib.util.spec_from_file_location("ingest_tariffs_under_test", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.load_contract_reference_data()
    return module


INGEST = load_ingest_module()


class TestDutchParsing:
    def test_parse_dutch_decimal(self):
        assert INGEST.parse_dutch_decimal("108,9000") == Decimal("108.9000")

    def test_parse_dutch_month(self):
        parsed = INGEST.parse_dutch_month("augustus 2025")
        assert parsed.yyyy_mm == "2025-08"


class TestContractTyping:
    def test_classify_contract_type(self):
        assert INGEST.classify_contract_type("Vast (3 jaar)") == "fixed"
        assert INGEST.classify_contract_type("Variabel (onbepaald)") == "variable"

    def test_parse_duration_months(self):
        assert INGEST.parse_duration_months("Vast (3 jaar)") == 36
        assert INGEST.parse_duration_months("Variabel (onbepaald)") is None


class TestNormalization:
    def test_modelcontract_is_accepted_base(self):
        normalized = INGEST.normalize_contract_name("Budget Energie", "Modelcontract")
        assert normalized.contract_base_name == "Modelcontract"
        assert normalized.normalization_status == "shared_rule"

    def test_engie_opgewekt_is_accepted_base(self):
        normalized = INGEST.normalize_contract_name(
            "Engie retail",
            "ENGIE opgewekt 1 jaar",
            contract_type="fixed",
            contract_duration_label="Vast (1 jaar)",
        )
        assert normalized.contract_base_name == "ENGIE opgewekt"
        assert normalized.normalization_status == "provider_rule"

    def test_numeric_contract_name_maps_to_provider_type_duration(self):
        normalized = INGEST.normalize_contract_name(
            "Greenchoice",
            "250",
            contract_type="fixed",
            contract_duration_label="Vast (2 jaar)",
        )
        assert normalized.contract_base_name == "Greenchoice Vast (2 jaar)"
        assert normalized.normalization_status == "shared_rule"

    def test_vaste_einddatum_maps_to_provider_duration(self):
        normalized = INGEST.normalize_contract_name(
            "Greenchoice",
            "Vaste Einddatum",
            contract_type="fixed",
            contract_duration_label="Vast (1 jaar)",
        )
        assert normalized.contract_base_name == "Greenchoice Vast (1 jaar)"
        assert normalized.normalization_status == "shared_rule"

    def test_duration_only_base_maps_to_provider_duration(self):
        normalized = INGEST.normalize_contract_name(
            "Om | nieuwe energie",
            "1 jaar vast",
            contract_type="fixed",
            contract_duration_label="Vast (1 jaar)",
        )
        assert normalized.contract_base_name == "Om nieuwe energie Vast (1 jaar)"
        assert normalized.normalization_status == "shared_rule"

    def test_variabel_maps_to_provider_duration(self):
        normalized = INGEST.normalize_contract_name(
            "Om | nieuwe energie",
            "Variabel",
            contract_type="variable",
            contract_duration_label="Variabel (onbepaald)",
        )
        assert normalized.contract_base_name == "Om nieuwe energie Variabel (onbepaald)"
        assert normalized.normalization_status == "shared_rule"

    def test_modifier_only_base_maps_to_provider_duration(self):
        normalized = INGEST.normalize_contract_name(
            "Greenchoice",
            "Variabel met Korting Start",
            contract_type="variable",
            contract_duration_label="Variabel (onbepaald)",
        )
        assert normalized.contract_base_name == "Greenchoice Variabel (onbepaald)"
        assert normalized.normalization_status == "shared_rule"

    def test_discount_amount_falls_back_to_meaningful_base(self):
        normalized = INGEST.normalize_contract_name(
            "Greenchoice",
            "Nederlands Groen 2 jaar + 300 euro Korting",
            contract_type="fixed",
            contract_duration_label="Vast (2 jaar)",
        )
        assert normalized.contract_base_name == "Nederlands Groen"

    def test_hezelaer_gezinsenergie_vastzeker_maps_to_vastzeker(self):
        normalized = INGEST.normalize_contract_name(
            "Hezelaer Energy",
            "Gezinsenergie VastZeker 3 jaar",
            contract_type="fixed",
            contract_duration_label="Vast (3 jaar)",
        )
        assert normalized.contract_base_name == "VastZeker"
        assert normalized.normalization_status == "provider_rule"

    def test_cleanenergy_base_normalizes_to_clean_energy(self):
        normalized = INGEST.normalize_contract_name(
            "Cleanenergy",
            "Clean Energy Huishoudelijk 1 jaar vast Energiekantoor.nl",
        )
        assert normalized.contract_name_no_variant == "Clean Energy Huishoudelijk 1 jaar vast"
        assert normalized.contract_base_name == "Clean Energy"
        assert normalized.variant == "Energiekantoor.nl"

    def test_frank_strips_month_suffix(self):
        normalized = INGEST.normalize_contract_name(
            "Frank energie",
            "Frank Energie Variabel Apr 2025",
        )
        assert normalized.contract_name_no_variant == "Frank Energie Variabel"
        assert normalized.contract_base_name == "Frank Energie Variabel"

    def test_energiedirect_bundle_normalizes_to_groene_stroom_en_gas(self):
        normalized = INGEST.normalize_contract_name(
            "Energiedirect.nl",
            "Groene Stroom en Gas DirectVoordeel Actie 1 jaar vast",
            contract_type="fixed",
            contract_duration_label="Vast (1 jaar)",
        )
        assert normalized.contract_base_name == "Groene Stroom en Gas"
        assert normalized.normalization_status == "provider_rule"

    def test_greenchoice_groenbezig_normalizes_to_groen_bezig(self):
        normalized = INGEST.normalize_contract_name(
            "Greenchoice",
            "Groenbezig 2 jaar",
            contract_type="fixed",
            contract_duration_label="Vast (2 jaar)",
        )
        assert normalized.contract_base_name == "Groen Bezig"
        assert normalized.normalization_status == "provider_rule"

    def test_coolblue_ing_puntenaanbod_maps_to_provider_duration(self):
        normalized = INGEST.normalize_contract_name(
            "Coolblue Energie",
            "ING Puntenaanbod",
            contract_type="fixed",
            contract_duration_label="Vast (1 jaar)",
        )
        assert normalized.contract_base_name == "Coolblue Energie Vast (1 jaar)"
        assert normalized.normalization_status == "provider_rule"


class TestKeyGeneration:
    def test_contract_snapshot_key_includes_duration(self):
        key = INGEST.generate_contract_snapshot_key(
            provider_id="greenchoice",
            contract_type="fixed",
            meter_type="double",
            contract_name_no_variant_slug="collectief_1_jaar",
            contract_duration_label="Vast (1 jaar)",
            variant=None,
            snapshot_month="2025-04",
        )
        assert "vast_1_jaar" in key

    def test_usage_key_includes_tariff_band(self):
        key = INGEST.generate_usage_key(
            "contract-key",
            "electricity",
            "import",
            "offpeak",
            "year",
        )
        assert key.endswith("|electricity|import|offpeak|year")


class TestTransformContract:
    def test_transform_variable_single_meter_uses_single_band(self):
        raw_record = {
            "provider": "AllureNRG",
            "contract_name": "Variabele Prijs (met zonnepanelen)",
            "contract_duration": "Variabel (onbepaald)",
            "meter_type": "single",
            "tariffs": {
                "gas": {
                    "fixed_yearly": "108,9000",
                    "variable_per_m3": "1,3167",
                },
                "electricity": {
                    "fixed_yearly": "363,0000",
                    "piek_per_kwh": "0,2862",
                    "dal_per_kwh": None,
                },
            },
            "estimated_annual_costs": "189",
            "_tupleId": "8",
            "_month_idx": "augustus 2025",
            "_session_id": "SESSION123",
        }

        result = INGEST.transform_contract(raw_record, Path("contracts_augustus 2025.json"))

        assert result.contract_row.contract_type == "variable"
        assert result.contract_row.snapshot_month == "2025-08"
        assert result.contract_row.contract_snapshot_key.endswith("|2025-08")
        assert any(row.tariff_band == "single" for row in result.usage_rows if row.commodity == "electricity")
        assert any(row.tariff_band == "single" for row in result.usage_rows if row.commodity == "gas")


class TestParquetRoundTrip:
    def test_parquet_deduplication(self):
        contract_row = INGEST.ContractRow(
            contract_snapshot_key="test|fixed|single|plan|vast_1_jaar|none|2025-08",
            contract_base_key="test|plan",
            provider_id="test",
            provider_name="Test",
            raw_contract_name="Plan 1 jaar",
            contract_name_no_variant="Plan 1 jaar",
            contract_name_no_variant_slug="plan_1_jaar",
            contract_base_name="Plan",
            contract_base_slug="plan",
            variant=None,
            contract_type="fixed",
            contract_duration_label="Vast (1 jaar)",
            duration_months=12,
            meter_type="single",
            has_gas=False,
            has_electricity=True,
            snapshot_month="2025-08",
            source_file="test.json",
            source_session_id="s",
            source_tuple_id="t",
            estimated_annual_costs="100",
            normalization_status="provider_rule",
            normalization_rule="test_rule",
        )

        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "contracts_fixed.parquet"
            count_1 = INGEST.write_or_merge_parquet(
                output_path,
                [contract_row],
                INGEST.get_contracts_schema(),
                dedup_keys=["contract_snapshot_key"],
            )
            count_2 = INGEST.write_or_merge_parquet(
                output_path,
                [contract_row],
                INGEST.get_contracts_schema(),
                dedup_keys=["contract_snapshot_key"],
            )

            assert count_1 == 1
            assert count_2 == 1
