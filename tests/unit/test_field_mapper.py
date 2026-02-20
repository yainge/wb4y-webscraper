"""Tests for normalizer/field_mapper.py."""
from __future__ import annotations

from wb4u_scraper.normalizer.field_mapper import (
    infer_meter_direction,
    infer_tou_from_columns,
    map_columns,
    normalize_commodity,
    normalize_contract_type,
)


class TestMapColumns:
    def test_maps_dutch_columns(self):
        raw = ["Leverancier", "Contractnaam", "Tarief", "Peildatum", "Energiesoort"]
        result = map_columns(raw)
        assert result == {
            "Leverancier": "provider_name",
            "Contractnaam": "contract_name",
            "Tarief": "value",
            "Peildatum": "valid_from",
            "Energiesoort": "commodity",
        }

    def test_case_insensitive(self):
        result = map_columns(["LEVERANCIER", "contractnaam"])
        assert "LEVERANCIER" in result
        assert "contractnaam" in result

    def test_strips_tableau_wrappers(self):
        result = map_columns(["ATTR(Leverancier)", "SUM(Tarief)"])
        assert result["ATTR(Leverancier)"] == "provider_name"
        assert result["SUM(Tarief)"] == "value"

    def test_unmapped_columns_skipped(self):
        result = map_columns(["Leverancier", "SomeRandomColumn"])
        assert len(result) == 1
        assert "SomeRandomColumn" not in result

    def test_fixed_cost_mapping(self):
        result = map_columns(["Vaste kosten", "Vastrecht"])
        assert result["Vaste kosten"] == "fixed_cost_value"
        assert result["Vastrecht"] == "fixed_cost_value"


class TestNormalizeContractType:
    def test_variabel(self):
        assert normalize_contract_type("variabel") == "variable"

    def test_vast(self):
        assert normalize_contract_type("vast") == "fixed"

    def test_dynamisch(self):
        assert normalize_contract_type("dynamisch") == "dynamic"

    def test_hybride(self):
        assert normalize_contract_type("hybride") == "hybrid"

    def test_unknown_fallback(self):
        assert normalize_contract_type("onbekend") == "unknown"

    def test_whitespace_handling(self):
        assert normalize_contract_type("  variabel  ") == "variable"


class TestNormalizeCommodity:
    def test_elektriciteit(self):
        assert normalize_commodity("elektriciteit") == "electricity"

    def test_stroom(self):
        assert normalize_commodity("stroom") == "electricity"

    def test_gas(self):
        assert normalize_commodity("gas") == "gas"

    def test_aardgas(self):
        assert normalize_commodity("aardgas") == "gas"

    def test_stadswarmte(self):
        assert normalize_commodity("stadswarmte") == "district_heating"

    def test_unknown_passthrough(self):
        assert normalize_commodity("something_else") == "something_else"


class TestInferTou:
    def test_hoog_is_on_peak(self):
        assert infer_tou_from_columns("Tarief hoog") == "on_peak"

    def test_dal_is_off_peak(self):
        assert infer_tou_from_columns("Tarief dal") == "off_peak"

    def test_normal_is_flat(self):
        assert infer_tou_from_columns("Tarief") == "flat"


class TestInferMeterDirection:
    def test_teruglevering_is_feed_in(self):
        assert infer_meter_direction("Teruglevertarief") == "feed_in"

    def test_normal_is_consumption(self):
        assert infer_meter_direction("Leveringstarief") == "consumption"

    def test_context_feed_in(self):
        assert infer_meter_direction("Tarief", "teruglevering") == "feed_in"
