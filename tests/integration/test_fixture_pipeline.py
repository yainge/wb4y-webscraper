"""Integration test: full pipeline from raw JSON fixtures → normalize → validate → local export."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from wb4u_scraper.config import ScraperSettings
from wb4u_scraper.exporter.local_exporter import export_local
from wb4u_scraper.exporter.raw_exporter import save_raw_snapshot
from wb4u_scraper.models.run_metadata import RunMetadata
from wb4u_scraper.normalizer.transform import normalize_raw_snapshot
from wb4u_scraper.validator.pandera_schemas import normalized_schema
from wb4u_scraper.validator.rules import validate_normalized


@pytest.mark.integration
class TestFixturePipeline:
    def test_full_pipeline_from_fixture(
        self,
        raw_tableau_sample: dict,
        settings: ScraperSettings,
        run_meta: RunMetadata,
    ):
        """Exercise normalize → validate → export with stored fixture data."""
        # ── RAW EXPORT ──────────────────────────────────────────────
        raw_dir, snapshot_hash = save_raw_snapshot(
            settings=settings,
            run_meta=run_meta,
            worksheets=raw_tableau_sample,
        )
        assert raw_dir.exists()
        assert (raw_dir / "metadata.json").exists()
        assert (raw_dir / "content_hashes.json").exists()
        assert snapshot_hash

        # Verify content hashes
        hashes = json.loads((raw_dir / "content_hashes.json").read_text())
        assert len(hashes) > 0

        # ── NORMALIZE ───────────────────────────────────────────────
        records = normalize_raw_snapshot(raw_tableau_sample, run_meta.started_at_utc)
        assert len(records) > 0

        # ── VALIDATE (business rules) ──────────────────────────────
        report = validate_normalized(records)
        assert not report.has_critical_errors

        # ── VALIDATE (pandera) ──────────────────────────────────────
        df = pd.DataFrame([r.to_dict() for r in records])
        validated_df = normalized_schema.validate(df)
        assert len(validated_df) == len(records)

        # ── LOCAL EXPORT ────────────────────────────────────────────
        written = export_local(records, run_meta.run_id, settings)
        assert "parquet" in written
        assert "jsonl" in written
        assert written["parquet"].exists()
        assert written["jsonl"].exists()

        # Verify parquet is readable
        df_back = pd.read_parquet(written["parquet"])
        assert len(df_back) == len(records)

        # Verify jsonl line count
        lines = written["jsonl"].read_text().strip().split("\n")
        assert len(lines) == len(records)

    def test_all_expected_providers_present(self, raw_tableau_sample):
        """Verify all providers from fixture appear in normalized output."""
        records = normalize_raw_snapshot(raw_tableau_sample, "2025-01-15T12:00:00+00:00")
        providers = {r.provider_name for r in records}
        assert providers == {"Eneco", "Vattenfall", "Essent", "Greenchoice"}

    def test_electricity_and_gas_present(self, raw_tableau_sample):
        """Verify both commodities are present."""
        records = normalize_raw_snapshot(raw_tableau_sample, "2025-01-15T12:00:00+00:00")
        commodities = {r.commodity for r in records}
        assert "electricity" in commodities
        assert "gas" in commodities

    def test_fixed_and_variable_contracts_present(self, raw_tableau_sample):
        """Verify both contract types from fixture appear."""
        records = normalize_raw_snapshot(raw_tableau_sample, "2025-01-15T12:00:00+00:00")
        types = {r.contract_type for r in records}
        assert "variable" in types
        assert "fixed" in types

    def test_symlinks_created(self, raw_tableau_sample, settings, run_meta):
        """Verify latest symlinks are created."""
        records = normalize_raw_snapshot(raw_tableau_sample, run_meta.started_at_utc)
        export_local(records, run_meta.run_id, settings)

        norm_dir = settings.data_dir / "normalized"
        latest_parquet = norm_dir / "prices_latest.parquet"
        latest_jsonl = norm_dir / "prices_latest.jsonl"
        assert latest_parquet.is_symlink()
        assert latest_jsonl.is_symlink()
