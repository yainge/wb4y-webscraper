"""Tests for normalizer/transform.py."""
from __future__ import annotations

from wb4u_scraper.normalizer.transform import normalize_raw_snapshot


class TestNormalizeRawSnapshot:
    def test_basic_normalization(self, raw_tableau_sample):
        records = normalize_raw_snapshot(raw_tableau_sample, "2025-01-15T12:00:00+00:00")
        assert len(records) > 0

        # Each row with a value + fixed cost should produce 2 records
        providers = {r.provider_name for r in records}
        assert "Eneco" in providers
        assert "Vattenfall" in providers

    def test_contract_type_normalized(self, raw_tableau_sample):
        records = normalize_raw_snapshot(raw_tableau_sample, "2025-01-15T12:00:00+00:00")
        types = {r.contract_type for r in records}
        # "variabel" → "variable", "vast" → "fixed"
        assert "variable" in types
        assert "fixed" in types
        assert "variabel" not in types
        assert "vast" not in types

    def test_commodity_normalized(self, raw_tableau_sample):
        records = normalize_raw_snapshot(raw_tableau_sample, "2025-01-15T12:00:00+00:00")
        commodities = {r.commodity for r in records}
        assert "electricity" in commodities
        assert "gas" in commodities
        assert "elektriciteit" not in commodities

    def test_fixed_cost_separate_record(self, raw_tableau_sample):
        records = normalize_raw_snapshot(raw_tableau_sample, "2025-01-15T12:00:00+00:00")
        monthly = [r for r in records if r.unit == "eur_per_month"]
        assert len(monthly) > 0
        for r in monthly:
            assert r.value > 0

    def test_content_hash_set(self, raw_tableau_sample):
        records = normalize_raw_snapshot(raw_tableau_sample, "2025-01-15T12:00:00+00:00")
        for r in records:
            assert r.content_hash, f"content_hash empty for {r.provider_name}"

    def test_valid_from_parsed(self, raw_tableau_sample):
        records = normalize_raw_snapshot(raw_tableau_sample, "2025-01-15T12:00:00+00:00")
        for r in records:
            assert r.valid_from is not None
            assert r.valid_from.startswith("2025-")

    def test_empty_worksheets(self):
        records = normalize_raw_snapshot({}, "2025-01-15T12:00:00+00:00")
        assert records == []

    def test_empty_rows(self):
        records = normalize_raw_snapshot({"sheet1": []}, "2025-01-15T12:00:00+00:00")
        assert records == []

    def test_gas_unit_inferred(self, raw_tableau_sample):
        records = normalize_raw_snapshot(raw_tableau_sample, "2025-01-15T12:00:00+00:00")
        gas_tariffs = [r for r in records if r.commodity == "gas" and r.unit != "eur_per_month"]
        for r in gas_tariffs:
            assert r.unit == "eur_per_m3"
