"""Low-level TableauScraper wrapper with retry, delay, and polite UA."""
from __future__ import annotations

import time
from typing import Any

import structlog
from tableauscraper import TableauScraper as TS
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from wb4u_scraper.config import ScraperSettings

logger = structlog.get_logger()

USER_AGENT = "WB4U-Scraper/0.1 (+https://github.com/wb4u/webscrapper)"


class TableauClientError(Exception):
    """Raised when Tableau extraction fails after retries."""


class TableauClient:
    """Thin wrapper around TableauScraper with retry logic and polite delays."""

    def __init__(self, settings: ScraperSettings) -> None:
        self._settings = settings
        self._delay_s = settings.tableau_delay_ms / 1000.0
        self._ts = TS()
        self._ts.headers = {"User-Agent": USER_AGENT}
        self._workbook: Any | None = None

    @property
    def workbook(self) -> Any:
        if self._workbook is None:
            raise TableauClientError("Not connected. Call connect() first.")
        return self._workbook

    def connect(self) -> Any:
        """Load the Tableau workbook from the configured URL."""
        url = self._settings.tableau_url
        logger.info("tableau_connect", url=url)

        try:
            wb = self._connect_with_retry(url)
        except RetryError as exc:
            raise TableauClientError(
                f"Failed to connect to Tableau after {self._settings.retry_max_attempts} attempts"
            ) from exc

        self._workbook = wb
        sheet_names = [ws.name for ws in wb.worksheets]
        logger.info("tableau_connected", sheets=sheet_names, sheet_count=len(sheet_names))
        return wb

    def get_worksheets(self) -> list[Any]:
        """Return all worksheets from the loaded workbook."""
        return self.workbook.worksheets

    def get_worksheet_data(self, worksheet: Any) -> list[dict[str, Any]]:
        """Extract rows from a single worksheet as list of dicts."""
        self._polite_delay()
        try:
            df = worksheet.data
            if df.empty:
                logger.warning("worksheet_empty", worksheet=worksheet.name)
                return []
            records = df.to_dict(orient="records")
            logger.info(
                "worksheet_extracted",
                worksheet=worksheet.name,
                row_count=len(records),
                columns=list(df.columns),
            )
            return records
        except Exception as exc:
            logger.error("worksheet_extraction_failed", worksheet=worksheet.name, error=str(exc))
            raise

    def get_storypoints(self) -> list[Any]:
        """Get available storypoints (tabs) from the workbook."""
        try:
            return self.workbook.getStoryPoints() or []
        except Exception:
            logger.debug("no_storypoints_available")
            return []

    def go_to_storypoint(self, index: int) -> Any:
        """Navigate to a specific storypoint and return the resulting workbook."""
        self._polite_delay()
        logger.info("tableau_storypoint", index=index)
        try:
            wb = self.workbook.goToStoryPoint(index)
            self._workbook = wb
            return wb
        except Exception as exc:
            logger.error("storypoint_navigation_failed", index=index, error=str(exc))
            raise

    def set_parameter(self, name: str, value: str) -> Any:
        """Set a Tableau parameter (e.g., date selector) and return updated workbook."""
        self._polite_delay()
        logger.info("tableau_set_parameter", name=name, value=value)
        try:
            wb = self.workbook.setParameter(name, value)
            self._workbook = wb
            return wb
        except Exception as exc:
            logger.warning("set_parameter_failed", name=name, value=value, error=str(exc))
            raise

    def _polite_delay(self) -> None:
        time.sleep(self._delay_s)

    def _connect_with_retry(self, url: str) -> Any:
        """Inner connection method with tenacity retry."""
        max_attempts = self._settings.retry_max_attempts
        base_wait = self._settings.retry_base_wait_seconds
        max_wait = self._settings.retry_max_wait_seconds

        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=base_wait, max=max_wait),
            retry=retry_if_exception_type(Exception),
            before_sleep=lambda rs: logger.warning(
                "tableau_retry",
                attempt=rs.attempt_number,
                wait=rs.next_action.sleep,
            ),
        )
        def _do_connect() -> Any:
            self._ts.loads(url)
            return self._ts.getWorkbook()

        return _do_connect()
