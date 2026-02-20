from __future__ import annotations

from pathlib import Path

from wb4u_scraper.config import ScraperSettings


def raw_dir(settings: ScraperSettings, run_id: str) -> Path:
    p = settings.data_dir / "raw" / "tableau" / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def normalized_dir(settings: ScraperSettings) -> Path:
    p = settings.data_dir / "normalized"
    p.mkdir(parents=True, exist_ok=True)
    return p


def excel_dir(settings: ScraperSettings) -> Path:
    p = settings.exports_dir / "excel"
    p.mkdir(parents=True, exist_ok=True)
    return p


def baseline_path(settings: ScraperSettings) -> Path:
    return settings.data_dir / "raw" / "tableau" / "dashboard_structure_baseline.json"


def latest_raw_dir(settings: ScraperSettings) -> Path | None:
    """Find the most recent raw snapshot directory."""
    base = settings.data_dir / "raw" / "tableau"
    if not base.exists():
        return None
    dirs = sorted(
        [d for d in base.iterdir() if d.is_dir() and not d.name.startswith(".")],
        reverse=True,
    )
    return dirs[0] if dirs else None
