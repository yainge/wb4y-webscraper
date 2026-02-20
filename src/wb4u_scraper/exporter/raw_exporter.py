"""Save raw Tableau extracts to disk: JSON per worksheet + metadata + content hashes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from wb4u_scraper.config import ScraperSettings
from wb4u_scraper.models.run_metadata import RunMetadata
from wb4u_scraper.normalizer.drift_detector import DashboardStructure, DriftReport
from wb4u_scraper.utils.hashing import hash_file
from wb4u_scraper.utils.paths import raw_dir

logger = structlog.get_logger()


def save_raw_snapshot(
    *,
    settings: ScraperSettings,
    run_meta: RunMetadata,
    worksheets: dict[str, list[dict[str, Any]]],
    dashboard_structure: DashboardStructure | None = None,
    drift_report: DriftReport | None = None,
) -> tuple[Path, str]:
    """Persist raw worksheet data and metadata to disk.

    Returns:
        Tuple of (snapshot directory path, aggregate content hash).
    """
    out_dir = raw_dir(settings, run_meta.run_id)
    logger.info("raw_export_start", dir=str(out_dir), worksheet_count=len(worksheets))

    # Write each worksheet as JSON
    for ws_name, rows in worksheets.items():
        safe_name = _safe_filename(ws_name)
        ws_path = out_dir / f"{safe_name}.json"
        ws_path.write_text(json.dumps(rows, default=str, ensure_ascii=False, indent=2))

    # Build metadata
    metadata: dict[str, Any] = {
        "run_id": run_meta.run_id,
        "scraped_at": run_meta.started_at_utc,
        "source_url": settings.tableau_url,
        "worksheet_names": list(worksheets.keys()),
        "row_counts": {name: len(rows) for name, rows in worksheets.items()},
    }
    if dashboard_structure:
        metadata["dashboard_structure"] = dashboard_structure.to_dict()
    if drift_report:
        metadata["drift_report"] = drift_report.to_dict()

    meta_path = out_dir / "metadata.json"
    meta_path.write_text(json.dumps(metadata, default=str, ensure_ascii=False, indent=2))

    # Compute and save content hashes
    content_hashes: dict[str, str] = {}
    for f in sorted(out_dir.iterdir()):
        if f.is_file() and f.name != "content_hashes.json":
            content_hashes[f.name] = hash_file(str(f))

    hashes_path = out_dir / "content_hashes.json"
    hashes_path.write_text(json.dumps(content_hashes, indent=2))

    # Aggregate hash for the whole snapshot
    aggregate = "|".join(f"{k}:{v}" for k, v in sorted(content_hashes.items()))
    from wb4u_scraper.utils.hashing import sha256_of_string

    snapshot_hash = sha256_of_string(aggregate)

    logger.info(
        "raw_export_complete",
        dir=str(out_dir),
        files=len(content_hashes),
        snapshot_hash=snapshot_hash[:16],
    )
    return out_dir, snapshot_hash


def _safe_filename(name: str) -> str:
    """Sanitize a worksheet name for use as a filename."""
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name).strip("_")[:200]
