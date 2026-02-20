"""ACM dashboard discovery — enumerate sheets, storypoints, worksheets, and columns."""
from __future__ import annotations

from typing import Any

import structlog

from wb4u_scraper.normalizer.drift_detector import DashboardStructure
from wb4u_scraper.scraper.tableau_client import TableauClient

logger = structlog.get_logger()


class DashboardNavigator:
    """Discover the structure of the ACM Tableau dashboard."""

    def __init__(self, client: TableauClient) -> None:
        self._client = client

    def discover_structure(self) -> DashboardStructure:
        """Walk through storypoints/worksheets and catalog the full dashboard structure."""
        structure = DashboardStructure()

        storypoints = self._client.get_storypoints()

        if storypoints:
            structure.sheets = [sp.get("storyPointCaption", f"sp_{i}") for i, sp in enumerate(storypoints)]
            logger.info("dashboard_storypoints_found", count=len(storypoints))

            for i, sp in enumerate(storypoints):
                caption = sp.get("storyPointCaption", f"sp_{i}")
                try:
                    self._client.go_to_storypoint(i)
                    ws_list = self._client.get_worksheets()
                    ws_names = [ws.name for ws in ws_list]
                    structure.worksheets_per_sheet[caption] = ws_names

                    for ws in ws_list:
                        self._catalog_worksheet_columns(ws, structure)

                except Exception as exc:
                    logger.warning("storypoint_discovery_failed", index=i, caption=caption, error=str(exc))
        else:
            # No storypoints — treat the single workbook view as one sheet
            logger.info("dashboard_no_storypoints", msg="single workbook view")
            structure.sheets = ["default"]
            ws_list = self._client.get_worksheets()
            ws_names = [ws.name for ws in ws_list]
            structure.worksheets_per_sheet["default"] = ws_names

            for ws in ws_list:
                self._catalog_worksheet_columns(ws, structure)

        logger.info(
            "dashboard_structure_discovered",
            sheets=len(structure.sheets),
            worksheets=sum(len(v) for v in structure.worksheets_per_sheet.values()),
            cataloged_columns=len(structure.columns_per_worksheet),
        )
        return structure

    def extract_all_worksheets(self) -> dict[str, list[dict[str, Any]]]:
        """Extract data from all worksheets across all storypoints.

        Returns a dict mapping worksheet name → list of row dicts.
        """
        all_data: dict[str, list[dict[str, Any]]] = {}
        storypoints = self._client.get_storypoints()

        if storypoints:
            for i, sp in enumerate(storypoints):
                caption = sp.get("storyPointCaption", f"sp_{i}")
                try:
                    self._client.go_to_storypoint(i)
                    self._extract_current_worksheets(all_data, prefix=caption)
                except Exception as exc:
                    logger.warning("storypoint_extract_failed", index=i, caption=caption, error=str(exc))
        else:
            self._extract_current_worksheets(all_data)

        logger.info(
            "all_worksheets_extracted",
            worksheet_count=len(all_data),
            total_rows=sum(len(v) for v in all_data.values()),
        )
        return all_data

    def _extract_current_worksheets(
        self,
        target: dict[str, list[dict[str, Any]]],
        prefix: str = "",
    ) -> None:
        """Extract all worksheets from the current workbook state."""
        for ws in self._client.get_worksheets():
            ws_key = f"{prefix}/{ws.name}" if prefix else ws.name
            if ws_key in target:
                logger.debug("worksheet_already_extracted", worksheet=ws_key)
                continue
            try:
                rows = self._client.get_worksheet_data(ws)
                if rows:
                    target[ws_key] = rows
            except Exception as exc:
                logger.warning("worksheet_extract_failed", worksheet=ws_key, error=str(exc))

    def _catalog_worksheet_columns(self, ws: Any, structure: DashboardStructure) -> None:
        """Record column names for a worksheet (uses .data to peek at columns)."""
        try:
            df = ws.data
            if not df.empty:
                structure.columns_per_worksheet[ws.name] = list(df.columns)
        except Exception as exc:
            logger.debug("column_catalog_failed", worksheet=ws.name, error=str(exc))
