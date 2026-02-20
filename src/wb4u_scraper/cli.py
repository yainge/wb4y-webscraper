"""CLI entrypoint: wb4u-scraper run | validate | backfill | db-migrate."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import structlog
import typer

app = typer.Typer(name="wb4u-scraper", help="ACM Tableau contract price scraper for WB4U.")
logger = structlog.get_logger()


@app.command()
def run(
    dry_run: bool = typer.Option(False, "--dry-run", help="Skip DB publish, just extract + normalize + local export."),
    skip_scrape: bool = typer.Option(False, "--skip-scrape", help="Skip extraction, re-normalize latest raw snapshot."),
    fallback: bool = typer.Option(False, "--fallback", help="Use Playwright fallback instead of TableauScraper."),
) -> None:
    """Run the full scrape → normalize → validate → publish pipeline."""
    from wb4u_scraper.config import get_settings
    from wb4u_scraper.logging_setup import configure_logging

    settings = get_settings()
    configure_logging(settings)

    from wb4u_scraper.exporter.local_exporter import export_local
    from wb4u_scraper.exporter.raw_exporter import save_raw_snapshot
    from wb4u_scraper.models.run_metadata import create_run_metadata
    from wb4u_scraper.normalizer.transform import normalize_raw_snapshot
    from wb4u_scraper.validator.pandera_schemas import normalized_schema
    from wb4u_scraper.validator.rules import validate_normalized

    run_meta = create_run_metadata()
    logger.info("pipeline_start", run_id=run_meta.run_id, dry_run=dry_run)

    try:
        # ── EXTRACT ─────────────────────────────────────────────────
        if skip_scrape:
            worksheets, dashboard_structure, drift_report, raw_snapshot_hash = _load_latest_snapshot(settings)
        else:
            from wb4u_scraper.scraper.extraction import run_extraction

            extraction = run_extraction(settings, use_fallback=fallback)
            worksheets = extraction.worksheets
            dashboard_structure = extraction.dashboard_structure
            drift_report = extraction.drift_report

            # Save raw snapshot
            _, raw_snapshot_hash = save_raw_snapshot(
                settings=settings,
                run_meta=run_meta,
                worksheets=worksheets,
                dashboard_structure=dashboard_structure,
                drift_report=drift_report,
            )

        if not worksheets:
            logger.error("no_worksheets_extracted")
            run_meta.mark_failed("No worksheets extracted")
            raise typer.Exit(1)

        # ── NORMALIZE ───────────────────────────────────────────────
        records = normalize_raw_snapshot(worksheets, run_meta.started_at_utc)
        logger.info("normalize_done", record_count=len(records))

        if not records:
            logger.error("no_records_normalized")
            run_meta.mark_failed("No records after normalization")
            raise typer.Exit(1)

        # ── VALIDATE ────────────────────────────────────────────────
        report = validate_normalized(records)
        report.log_summary()

        # Pandera validation
        df = pd.DataFrame([r.to_dict() for r in records])
        try:
            normalized_schema.validate(df)
            logger.info("pandera_validation_passed")
        except Exception as exc:
            logger.error("pandera_validation_failed", error=str(exc))
            if report.has_critical_errors:
                run_meta.mark_failed(f"Validation failed: {report.error_count} errors")
                raise typer.Exit(1)

        # ── LOCAL EXPORT ────────────────────────────────────────────
        written = export_local(records, run_meta.run_id, settings)
        logger.info("local_export_done", files=list(written.keys()))

        # ── DB PUBLISH ──────────────────────────────────────────────
        if not dry_run and settings.database_url:
            from wb4u_scraper.exporter.db_publisher import DBPublisher

            publisher = DBPublisher(settings)
            publisher.ensure_tables()
            upserted = publisher.publish(
                run_meta=run_meta,
                records=records,
                settings=settings,
                dashboard_structure=dashboard_structure if not skip_scrape else None,
                drift_report=drift_report if not skip_scrape else None,
                raw_snapshot_hash=raw_snapshot_hash if not skip_scrape else "",
            )
            run_meta.mark_complete(record_count=len(records))
            publisher.mark_run_complete(run_meta)
            logger.info("db_publish_done", upserted=upserted)
        else:
            run_meta.mark_complete(record_count=len(records))
            if dry_run:
                logger.info("dry_run_complete", record_count=len(records))
            else:
                logger.warning("db_publish_skipped", reason="no DATABASE_URL configured")

    except typer.Exit:
        raise
    except Exception as exc:
        logger.error("pipeline_failed", error=str(exc), exc_info=True)
        run_meta.mark_failed(str(exc))

        # Try to persist failure to DB
        if not dry_run and settings.database_url:
            try:
                from wb4u_scraper.exporter.db_publisher import DBPublisher

                publisher = DBPublisher(settings)
                publisher.mark_run_failed(run_meta, str(exc))
            except Exception:
                pass

        raise typer.Exit(1)


@app.command()
def validate(
    path: Optional[Path] = typer.Argument(None, help="Path to parquet or jsonl file. Defaults to latest."),
) -> None:
    """Validate a normalized dataset (parquet or jsonl) against schema and business rules."""
    from wb4u_scraper.config import get_settings
    from wb4u_scraper.logging_setup import configure_logging

    settings = get_settings()
    configure_logging(settings)

    from wb4u_scraper.models.price_observation import PriceObservation
    from wb4u_scraper.validator.pandera_schemas import normalized_schema
    from wb4u_scraper.validator.rules import validate_normalized

    if path is None:
        path = settings.data_dir / "normalized" / "prices_latest.parquet"

    if not path.exists():
        logger.error("file_not_found", path=str(path))
        raise typer.Exit(1)

    # Load records
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    elif path.suffix == ".jsonl":
        import json

        rows = []
        with open(path) as f:
            for line in f:
                rows.append(json.loads(line))
        df = pd.DataFrame(rows)
    else:
        logger.error("unsupported_format", suffix=path.suffix)
        raise typer.Exit(1)

    logger.info("validating_file", path=str(path), rows=len(df))

    # Pandera
    try:
        normalized_schema.validate(df)
        logger.info("pandera_ok")
    except Exception as exc:
        logger.error("pandera_failed", error=str(exc))

    # Business rules
    records = [PriceObservation(**row) for _, row in df.iterrows()]
    report = validate_normalized(records)
    report.log_summary()

    if report.has_critical_errors:
        raise typer.Exit(1)

    typer.echo(f"Validation passed: {report.total_records} records, {report.warning_count} warnings.")


@app.command()
def backfill(
    start: str = typer.Option(..., help="Start month (YYYY-MM)."),
    end: str = typer.Option(..., help="End month (YYYY-MM)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Skip DB publish."),
) -> None:
    """Re-process and publish historical data from stored raw snapshots."""
    from wb4u_scraper.config import get_settings
    from wb4u_scraper.logging_setup import configure_logging

    settings = get_settings()
    configure_logging(settings)

    import json

    from wb4u_scraper.exporter.local_exporter import export_local
    from wb4u_scraper.models.run_metadata import create_run_metadata
    from wb4u_scraper.normalizer.transform import normalize_raw_snapshot
    from wb4u_scraper.validator.rules import validate_normalized

    raw_base = settings.data_dir / "raw" / "tableau"
    if not raw_base.exists():
        logger.error("no_raw_snapshots", path=str(raw_base))
        raise typer.Exit(1)

    snapshot_dirs = sorted(d for d in raw_base.iterdir() if d.is_dir() and not d.name.startswith("."))
    if not snapshot_dirs:
        logger.error("no_snapshot_dirs_found")
        raise typer.Exit(1)

    logger.info("backfill_start", start=start, end=end, snapshots=len(snapshot_dirs))
    total_records = 0

    for snap_dir in snapshot_dirs:
        meta_path = snap_dir / "metadata.json"
        if not meta_path.exists():
            continue

        # Load worksheets from snapshot
        worksheets: dict[str, list[dict]] = {}
        for f in snap_dir.iterdir():
            if f.suffix == ".json" and f.name not in ("metadata.json", "content_hashes.json"):
                worksheets[f.stem] = json.loads(f.read_text())

        if not worksheets:
            continue

        run_meta = create_run_metadata()
        records = normalize_raw_snapshot(worksheets, run_meta.started_at_utc)

        # Filter to date range
        records = [
            r for r in records if r.valid_from and start <= r.valid_from <= end + "-99"
        ]

        if not records:
            continue

        report = validate_normalized(records)
        if report.has_critical_errors:
            logger.warning("backfill_skip_snapshot", dir=snap_dir.name, errors=report.error_count)
            continue

        export_local(records, run_meta.run_id, settings)

        if not dry_run and settings.database_url:
            from wb4u_scraper.exporter.db_publisher import DBPublisher

            publisher = DBPublisher(settings)
            publisher.ensure_tables()
            publisher.publish(run_meta=run_meta, records=records, settings=settings)
            run_meta.mark_complete(record_count=len(records))
            publisher.mark_run_complete(run_meta)

        total_records += len(records)
        logger.info("backfill_snapshot_done", dir=snap_dir.name, records=len(records))

    logger.info("backfill_complete", total_records=total_records)


@app.command(name="db-migrate")
def db_migrate() -> None:
    """Run Alembic migrations to latest."""
    from wb4u_scraper.config import get_settings
    from wb4u_scraper.logging_setup import configure_logging

    settings = get_settings()
    configure_logging(settings)

    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(settings.project_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(settings.project_root / "migrations"))

    if settings.database_url:
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
    else:
        logger.error("no_database_url")
        raise typer.Exit(1)

    logger.info("running_migrations")
    command.upgrade(alembic_cfg, "head")
    logger.info("migrations_complete")


def _load_latest_snapshot(settings):
    """Load the most recent raw snapshot from disk."""
    import json

    from wb4u_scraper.utils.paths import latest_raw_dir

    snap_dir = latest_raw_dir(settings)
    if not snap_dir:
        raise RuntimeError("No raw snapshots found. Run without --skip-scrape first.")

    worksheets: dict[str, list[dict]] = {}
    for f in snap_dir.iterdir():
        if f.suffix == ".json" and f.name not in ("metadata.json", "content_hashes.json"):
            worksheets[f.stem] = json.loads(f.read_text())

    return worksheets, None, None, ""


if __name__ == "__main__":
    app()
