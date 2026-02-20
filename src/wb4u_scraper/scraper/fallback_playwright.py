"""Playwright-based fallback extractor for when TableauScraper cannot access the data.

This is a stub. Implement the full browser automation if TableauScraper fails
to access the ACM dashboard (e.g., embedded viz restrictions, JS-only rendering).
"""
from __future__ import annotations

from typing import Any

import structlog

from wb4u_scraper.config import ScraperSettings

logger = structlog.get_logger()


class PlaywrightExtractor:
    """Headless browser extraction using Playwright.

    Usage:
        extractor = PlaywrightExtractor(settings)
        data = extractor.extract()
    """

    def __init__(self, settings: ScraperSettings) -> None:
        self._settings = settings

    def extract(self) -> dict[str, list[dict[str, Any]]]:
        """Extract worksheet data via headless Chromium.

        Returns:
            Dict mapping worksheet name → list of row dicts.

        Raises:
            NotImplementedError: This is a stub — implement when needed.
        """
        raise NotImplementedError(
            "Playwright fallback is not yet implemented. "
            "The TableauScraper primary path should be used. "
            "If you're seeing this, TableauScraper couldn't access the dashboard. "
            "See PLAN.md section 1 for the fallback design."
        )
