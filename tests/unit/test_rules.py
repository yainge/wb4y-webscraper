"""Tests for validator/rules.py."""
from __future__ import annotations

from wb4u_scraper.models.price_observation import PriceObservation
from wb4u_scraper.validator.rules import validate_normalized


class TestValidateNormalized:
    def test_valid_records_no_errors(self, sample_observations):
        report = validate_normalized(sample_observations)
        assert not report.has_critical_errors
        assert report.total_records == len(sample_observations)

    def test_empty_provider_is_error(self):
        records = [
            PriceObservation(provider_name="", value=0.28, unit="eur_per_kwh"),
        ]
        report = validate_normalized(records)
        assert report.has_critical_errors
        assert report.error_count == 1

    def test_extreme_electricity_price_is_warning(self):
        records = [
            PriceObservation(
                provider_name="Test",
                value=5.00,
                unit="eur_per_kwh",
                meter_direction="consumption",
            ),
        ]
        report = validate_normalized(records)
        assert report.warning_count >= 1

    def test_normal_electricity_price_no_warning(self):
        records = [
            PriceObservation(
                provider_name="Test",
                value=0.30,
                unit="eur_per_kwh",
                meter_direction="consumption",
                valid_from="2025-01",
                contract_type="variable",
            ),
        ]
        report = validate_normalized(records)
        assert report.warning_count == 0

    def test_extreme_gas_price_is_warning(self):
        records = [
            PriceObservation(
                provider_name="Test",
                value=10.0,
                unit="eur_per_m3",
                valid_from="2025-01",
            ),
        ]
        report = validate_normalized(records)
        assert report.warning_count >= 1

    def test_missing_valid_from_is_warning(self):
        records = [
            PriceObservation(
                provider_name="Test",
                value=0.30,
                unit="eur_per_kwh",
                valid_from=None,
            ),
        ]
        report = validate_normalized(records)
        warnings = [i for i in report.issues if i.field == "valid_from"]
        assert len(warnings) == 1

    def test_unknown_contract_type_is_warning(self):
        records = [
            PriceObservation(
                provider_name="Test",
                value=0.30,
                contract_type="unknown",
                valid_from="2025-01",
            ),
        ]
        report = validate_normalized(records)
        warnings = [i for i in report.issues if i.field == "contract_type"]
        assert len(warnings) == 1

    def test_negative_feed_in_is_warning(self):
        records = [
            PriceObservation(
                provider_name="Test",
                value=-0.05,
                meter_direction="feed_in",
                valid_from="2025-01",
            ),
        ]
        report = validate_normalized(records)
        warnings = [i for i in report.issues if i.field == "value" and "feed-in" in i.message.lower()]
        assert len(warnings) == 1
