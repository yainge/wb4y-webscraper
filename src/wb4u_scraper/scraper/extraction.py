"""Orchestrator: connect → discover → drift-check → extract raw data."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from wb4u_scraper.config import ScraperSettings
from wb4u_scraper.normalizer.drift_detector import DashboardStructure, DriftReport, check_drift
from wb4u_scraper.scraper.dashboard_navigator import DashboardNavigator
from wb4u_scraper.scraper.tableau_client import TableauClient, TableauClientError

logger = structlog.get_logger()


@dataclass
class ExtractionResult:
    """All outputs from one extraction run."""

    worksheets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    dashboard_structure: DashboardStructure | None = None
    drift_report: DriftReport | None = None
    raw_snapshot_hash: str = ""


class ExtractionError(Exception):
    """Raised when the extraction pipeline encounters a fatal error."""


def run_extraction(settings: ScraperSettings, *, use_fallback: bool = False) -> ExtractionResult:
    """Execute the full extraction pipeline: connect → discover → drift → extract.

    Args:
        settings: Scraper configuration.
        use_fallback: If True, use Playwright fallback instead of TableauScraper.

    Returns:
        ExtractionResult with raw worksheet data and dashboard metadata.

    Raises:
        ExtractionError: On fatal connection or drift-breaking errors.
    """
    result = ExtractionResult()

    if use_fallback:
        return _run_fallback_extraction(settings, result)

    return _run_tableau_extraction(settings, result)


def _run_tableau_extraction(settings: ScraperSettings, result: ExtractionResult) -> ExtractionResult:
    """Primary extraction path using TableauScraper."""
    # 1. Connect
    client = TableauClient(settings)
    try:
        client.connect()
    except TableauClientError as exc:
        raise ExtractionError(f"Tableau connection failed: {exc}") from exc

    navigator = DashboardNavigator(client)

    # 2. Discover dashboard structure
    logger.info("extraction_discovering_structure")
    structure = navigator.discover_structure()
    result.dashboard_structure = structure

    # 3. Check for schema drift
    logger.info("extraction_checking_drift")
    drift = check_drift(structure, settings)
    result.drift_report = drift

    if drift.has_breaking_changes:
        logger.error("extraction_breaking_drift", summary=drift.summary)
        if settings.drift_fail_on_missing_columns:
            raise ExtractionError(f"Breaking schema drift detected: {drift.summary}")

    if drift.has_warnings:
        logger.warning("extraction_drift_warnings", summary=drift.summary)

    # 4. Extract all worksheet data
    logger.info("extraction_pulling_data")
    result.worksheets = navigator.extract_all_worksheets()

    logger.info(
        "extraction_complete",
        worksheet_count=len(result.worksheets),
        total_rows=sum(len(v) for v in result.worksheets.values()),
    )
    return result


def _run_fallback_extraction(settings: ScraperSettings, result: ExtractionResult) -> ExtractionResult:
    """Fallback extraction path using Playwright."""
    try:
        from wb4u_scraper.scraper.fallback_playwright import PlaywrightExtractor
    except ImportError as exc:
        raise ExtractionError(
            "Playwright not installed. Install with: pip install -e '.[fallback]'"
        ) from exc

    logger.info("extraction_using_fallback", method="playwright")
    extractor = PlaywrightExtractor(settings)
    result.worksheets = extractor.extract()

    logger.info(
        "fallback_extraction_complete",
        worksheet_count=len(result.worksheets),
        total_rows=sum(len(v) for v in result.worksheets.values()),
    )
    return result
