"""Tests for normalizer/drift_detector.py."""
from __future__ import annotations

from wb4u_scraper.config import ScraperSettings
from wb4u_scraper.normalizer.drift_detector import DashboardStructure, check_drift


class TestCheckDrift:
    def test_first_run_creates_baseline(self, settings: ScraperSettings):
        structure = DashboardStructure(
            sheets=["Sheet1"],
            worksheets_per_sheet={"Sheet1": ["WS1"]},
            columns_per_worksheet={"WS1": ["col_a", "col_b"]},
        )
        report = check_drift(structure, settings)

        # First run: no drift, baseline created
        assert not report.has_breaking_changes
        assert not report.has_warnings
        baseline = settings.data_dir / "raw" / "tableau" / "dashboard_structure_baseline.json"
        assert baseline.exists()

    def test_no_drift_on_same_structure(self, settings: ScraperSettings):
        structure = DashboardStructure(
            sheets=["Sheet1"],
            columns_per_worksheet={"WS1": ["col_a", "col_b"]},
        )
        # First run creates baseline
        check_drift(structure, settings)
        # Second run: no changes
        report = check_drift(structure, settings)
        assert not report.has_breaking_changes
        assert not report.has_warnings

    def test_new_sheet_is_warning(self, settings: ScraperSettings):
        original = DashboardStructure(sheets=["Sheet1"], columns_per_worksheet={"WS1": ["col_a"]})
        check_drift(original, settings)

        updated = DashboardStructure(sheets=["Sheet1", "Sheet2"], columns_per_worksheet={"WS1": ["col_a"]})
        report = check_drift(updated, settings)
        assert report.has_warnings
        assert "Sheet2" in report.new_sheets

    def test_missing_sheet_is_breaking(self, settings: ScraperSettings):
        original = DashboardStructure(sheets=["Sheet1", "Sheet2"], columns_per_worksheet={})
        check_drift(original, settings)

        updated = DashboardStructure(sheets=["Sheet1"], columns_per_worksheet={})
        report = check_drift(updated, settings)
        assert report.has_breaking_changes
        assert "Sheet2" in report.missing_sheets

    def test_new_column_is_warning(self, settings: ScraperSettings):
        original = DashboardStructure(sheets=["S1"], columns_per_worksheet={"WS1": ["col_a"]})
        check_drift(original, settings)

        updated = DashboardStructure(sheets=["S1"], columns_per_worksheet={"WS1": ["col_a", "col_b"]})
        report = check_drift(updated, settings)
        assert report.has_warnings
        assert "col_b" in report.new_columns.get("WS1", [])

    def test_missing_column_is_breaking(self, settings: ScraperSettings):
        original = DashboardStructure(sheets=["S1"], columns_per_worksheet={"WS1": ["col_a", "col_b"]})
        check_drift(original, settings)

        updated = DashboardStructure(sheets=["S1"], columns_per_worksheet={"WS1": ["col_a"]})
        report = check_drift(updated, settings)
        assert report.has_breaking_changes
        assert "col_b" in report.missing_columns.get("WS1", [])
