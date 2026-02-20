"""Export normalized PriceObservations to local Parquet and JSONL files."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import structlog

from wb4u_scraper.config import ScraperSettings
from wb4u_scraper.models.price_observation import PriceObservation
from wb4u_scraper.utils.paths import normalized_dir

logger = structlog.get_logger()


def export_local(
    records: list[PriceObservation],
    run_id: str,
    settings: ScraperSettings,
) -> dict[str, Path]:
    """Write normalized records to Parquet and JSONL.

    Returns:
        Dict with keys 'parquet' and 'jsonl' pointing to the written file paths.
    """
    out_dir = normalized_dir(settings)
    written: dict[str, Path] = {}

    if not records:
        logger.warning("local_export_skipped", reason="no records")
        return written

    dicts = [r.to_dict() for r in records]

    # Parquet
    if settings.write_parquet:
        parquet_path = out_dir / f"prices_{run_id}.parquet"
        df = pd.DataFrame(dicts)
        df.to_parquet(parquet_path, index=False, engine="pyarrow")
        written["parquet"] = parquet_path
        _update_symlink(out_dir / "prices_latest.parquet", parquet_path)
        logger.info("local_export_parquet", path=str(parquet_path), rows=len(df))

    # JSONL
    if settings.write_jsonl:
        jsonl_path = out_dir / f"prices_{run_id}.jsonl"
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for d in dicts:
                f.write(json.dumps(d, default=str, ensure_ascii=False) + "\n")
        written["jsonl"] = jsonl_path
        _update_symlink(out_dir / "prices_latest.jsonl", jsonl_path)
        logger.info("local_export_jsonl", path=str(jsonl_path), rows=len(dicts))

    return written


def _update_symlink(link_path: Path, target: Path) -> None:
    """Create or update a symlink to the latest file."""
    try:
        if link_path.is_symlink() or link_path.exists():
            link_path.unlink()
        link_path.symlink_to(target.name)
    except OSError as exc:
        logger.warning("symlink_update_failed", link=str(link_path), error=str(exc))
