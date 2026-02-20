"""Shared test fixtures."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wb4u_scraper.config import ScraperSettings
from wb4u_scraper.models.price_observation import PriceObservation
from wb4u_scraper.models.run_metadata import RunMetadata

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def raw_tableau_sample(fixtures_dir: Path) -> dict[str, list[dict]]:
    return json.loads((fixtures_dir / "raw_tableau_sample.json").read_text())


@pytest.fixture
def expected_normalized(fixtures_dir: Path) -> list[dict]:
    return json.loads((fixtures_dir / "expected_normalized.json").read_text())


@pytest.fixture
def settings(tmp_path: Path) -> ScraperSettings:
    """Settings pointing at a temp directory (no real DB)."""
    return ScraperSettings(
        data_dir=tmp_path / "data",
        exports_dir=tmp_path / "exports",
        database_url=None,
        log_level="DEBUG",
    )


@pytest.fixture
def run_meta() -> RunMetadata:
    return RunMetadata(run_id="20250101T000000_test1234")


@pytest.fixture
def sample_observations() -> list[PriceObservation]:
    """A small set of known-good PriceObservation records for testing."""
    return [
        PriceObservation(
            scraped_at_utc="2025-01-15T12:00:00+00:00",
            valid_from="2025-01",
            provider_name="Eneco",
            contract_name="Eneco Flexibel",
            contract_type="variable",
            commodity="electricity",
            meter_direction="consumption",
            tou="flat",
            unit="eur_per_kwh",
            value=0.28,
            content_hash="abc123",
        ),
        PriceObservation(
            scraped_at_utc="2025-01-15T12:00:00+00:00",
            valid_from="2025-01",
            provider_name="Eneco",
            contract_name="Eneco Flexibel",
            contract_type="variable",
            commodity="electricity",
            meter_direction="consumption",
            tou="flat",
            unit="eur_per_month",
            value=7.95,
            content_hash="def456",
        ),
        PriceObservation(
            scraped_at_utc="2025-01-15T12:00:00+00:00",
            valid_from="2025-01",
            provider_name="Eneco",
            contract_name="Eneco Flexibel",
            contract_type="variable",
            commodity="gas",
            meter_direction="consumption",
            tou="flat",
            unit="eur_per_m3",
            value=1.12,
            content_hash="ghi789",
        ),
    ]
