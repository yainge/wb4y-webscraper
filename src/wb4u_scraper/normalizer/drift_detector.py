from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json

import structlog

from wb4u_scraper.config import ScraperSettings

logger = structlog.get_logger()

BASELINE_FILE = "dashboard_structure_baseline.json"


@dataclass
class DriftReport:
    new_sheets: list[str] = field(default_factory=list)
    missing_sheets: list[str] = field(default_factory=list)
    new_worksheets: dict[str, list[str]] = field(default_factory=dict)
    missing_worksheets: dict[str, list[str]] = field(default_factory=dict)
    new_columns: dict[str, list[str]] = field(default_factory=dict)
    missing_columns: dict[str, list[str]] = field(default_factory=dict)
    summary: str = ""

    @property
    def has_breaking_changes(self) -> bool:
        return bool(self.missing_sheets or self.missing_columns)

    @property
    def has_warnings(self) -> bool:
        return bool(self.new_sheets or self.new_columns or self.new_worksheets)

    def to_dict(self) -> dict[str, Any]:
        return {
            "new_sheets": self.new_sheets,
            "missing_sheets": self.missing_sheets,
            "new_worksheets": self.new_worksheets,
            "missing_worksheets": self.missing_worksheets,
            "new_columns": self.new_columns,
            "missing_columns": self.missing_columns,
            "summary": self.summary,
        }


@dataclass
class DashboardStructure:
    """Captured structure of the ACM dashboard."""

    sheets: list[str] = field(default_factory=list)
    worksheets_per_sheet: dict[str, list[str]] = field(default_factory=dict)
    columns_per_worksheet: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sheets": self.sheets,
            "worksheets_per_sheet": self.worksheets_per_sheet,
            "columns_per_worksheet": self.columns_per_worksheet,
        }


def check_drift(
    current: DashboardStructure,
    settings: ScraperSettings,
) -> DriftReport:
    """Compare current dashboard structure against the stored baseline."""
    baseline_path = settings.data_dir / "raw" / "tableau" / BASELINE_FILE
    report = DriftReport()

    if not baseline_path.exists():
        _save_baseline(current, baseline_path)
        logger.info("drift_baseline_created", path=str(baseline_path))
        return report

    baseline = _load_baseline(baseline_path)

    # Compare sheets
    current_sheets = set(current.sheets)
    baseline_sheets = set(baseline.get("sheets", []))
    report.new_sheets = sorted(current_sheets - baseline_sheets)
    report.missing_sheets = sorted(baseline_sheets - current_sheets)

    # Compare columns per worksheet
    baseline_cols = baseline.get("columns_per_worksheet", {})
    for ws_name, current_cols in current.columns_per_worksheet.items():
        prev_cols = set(baseline_cols.get(ws_name, []))
        curr_cols = set(current_cols)
        new = sorted(curr_cols - prev_cols)
        missing = sorted(prev_cols - curr_cols)
        if new:
            report.new_columns[ws_name] = new
        if missing:
            report.missing_columns[ws_name] = missing

    # Build summary
    parts = []
    if report.missing_sheets:
        parts.append(f"Missing sheets: {report.missing_sheets}")
    if report.missing_columns:
        parts.append(f"Missing columns in: {list(report.missing_columns.keys())}")
    if report.new_sheets:
        parts.append(f"New sheets: {report.new_sheets}")
    if report.new_columns:
        parts.append(f"New columns in: {list(report.new_columns.keys())}")
    report.summary = "; ".join(parts) if parts else "No drift detected"

    # Update baseline
    _save_baseline(current, baseline_path)

    return report


def _save_baseline(structure: DashboardStructure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(structure.to_dict(), indent=2, ensure_ascii=False))


def _load_baseline(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())
