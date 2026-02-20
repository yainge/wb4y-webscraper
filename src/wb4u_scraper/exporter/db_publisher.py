"""Upsert normalized PriceObservations to Railway Postgres."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from wb4u_scraper.config import ScraperSettings
from wb4u_scraper.models.db_models import Base, ScraperPriceObservation, ScraperProviderContract, ScraperRun
from wb4u_scraper.models.price_observation import PriceObservation
from wb4u_scraper.models.run_metadata import RunMetadata
from wb4u_scraper.normalizer.drift_detector import DashboardStructure, DriftReport

logger = structlog.get_logger()


class DBPublisher:
    """Manages upsert of scraper results to Postgres."""

    def __init__(self, settings: ScraperSettings) -> None:
        if not settings.database_url:
            raise ValueError("DATABASE_URL not configured. Set WB4U_DATABASE_URL or DATABASE_URL env var.")
        self._engine = create_engine(settings.database_url, echo=False)
        self._session_factory = sessionmaker(bind=self._engine)

    def ensure_tables(self) -> None:
        """Create scraper_* tables if they don't exist (for quick setup without Alembic)."""
        Base.metadata.create_all(self._engine, checkfirst=True)
        logger.info("db_tables_ensured")

    def publish(
        self,
        *,
        run_meta: RunMetadata,
        records: list[PriceObservation],
        settings: ScraperSettings,
        dashboard_structure: DashboardStructure | None = None,
        drift_report: DriftReport | None = None,
        raw_snapshot_hash: str = "",
    ) -> int:
        """Upsert a complete scraper run to the database.

        Returns:
            Number of records upserted (inserted or updated).
        """
        with self._session_factory() as session:
            # 1. Register the run
            self._upsert_run(
                session,
                run_meta=run_meta,
                source_url=settings.tableau_url,
                record_count=len(records),
                raw_snapshot_hash=raw_snapshot_hash,
                dashboard_structure=dashboard_structure,
                drift_report=drift_report,
            )

            # 2. Upsert price observations
            upserted = self._upsert_observations(session, records, run_meta.run_id)

            # 3. Register provider contracts
            self._register_providers(session, records, run_meta.run_id)

            session.commit()
            logger.info("db_publish_complete", run_id=run_meta.run_id, upserted=upserted)
            return upserted

    def mark_run_complete(self, run_meta: RunMetadata) -> None:
        """Update the run record to completed status."""
        with self._session_factory() as session:
            run = session.get(ScraperRun, run_meta.run_id)
            if run:
                run.status = "completed"
                run.finished_at = datetime.now(timezone.utc)
                run.record_count = run_meta.record_count
                session.commit()

    def mark_run_failed(self, run_meta: RunMetadata, error: str) -> None:
        """Update the run record to failed status."""
        with self._session_factory() as session:
            run = session.get(ScraperRun, run_meta.run_id)
            if run:
                run.status = "failed"
                run.finished_at = datetime.now(timezone.utc)
                run.error_message = error
                session.commit()

    def _upsert_run(
        self,
        session: Session,
        *,
        run_meta: RunMetadata,
        source_url: str,
        record_count: int,
        raw_snapshot_hash: str,
        dashboard_structure: DashboardStructure | None,
        drift_report: DriftReport | None,
    ) -> None:
        """Insert or update the scraper_runs record."""
        existing = session.get(ScraperRun, run_meta.run_id)
        if existing:
            existing.record_count = record_count
            existing.raw_snapshot_hash = raw_snapshot_hash
            if dashboard_structure:
                existing.dashboard_structure = dashboard_structure.to_dict()
            if drift_report:
                existing.drift_report = drift_report.to_dict()
        else:
            run = ScraperRun(
                run_id=run_meta.run_id,
                source_url=source_url,
                record_count=record_count,
                raw_snapshot_hash=raw_snapshot_hash,
                dashboard_structure=dashboard_structure.to_dict() if dashboard_structure else None,
                drift_report=drift_report.to_dict() if drift_report else None,
            )
            session.add(run)

    def _upsert_observations(
        self,
        session: Session,
        records: list[PriceObservation],
        run_id: str,
    ) -> int:
        """Upsert price observations using ON CONFLICT DO UPDATE."""
        if not records:
            return 0

        upsert_sql = text("""
            INSERT INTO scraper_price_observations (
                run_id, content_hash, source, scraped_at, valid_from, valid_to,
                country, provider_name, contract_name, contract_type,
                commodity, meter_direction, tou, unit, value, currency,
                is_all_in, price_includes, notes, source_fields
            ) VALUES (
                :run_id, :content_hash, :source, :scraped_at, :valid_from, :valid_to,
                :country, :provider_name, :contract_name, :contract_type,
                :commodity, :meter_direction, :tou, :unit, :value, :currency,
                :is_all_in, :price_includes, :notes, :source_fields::jsonb
            )
            ON CONFLICT (provider_name, contract_name, contract_type, commodity,
                         meter_direction, tou, unit, valid_from)
            DO UPDATE SET
                value = EXCLUDED.value,
                content_hash = EXCLUDED.content_hash,
                run_id = EXCLUDED.run_id,
                scraped_at = EXCLUDED.scraped_at,
                source_fields = EXCLUDED.source_fields,
                updated_at = now()
            WHERE scraper_price_observations.content_hash != EXCLUDED.content_hash
        """)

        count = 0
        for rec in records:
            params = _observation_to_params(rec, run_id)
            result = session.execute(upsert_sql, params)
            count += result.rowcount

        logger.info("observations_upserted", total=len(records), changed=count)
        return count

    def _register_providers(
        self,
        session: Session,
        records: list[PriceObservation],
        run_id: str,
    ) -> None:
        """Register new provider/contract combos in scraper_provider_contracts."""
        seen: set[tuple[str, str, str, str]] = set()
        new_count = 0

        for rec in records:
            key = (rec.provider_name, rec.contract_name, rec.contract_type, rec.commodity)
            if key in seen:
                continue
            seen.add(key)

            # Check if already exists
            existing = (
                session.query(ScraperProviderContract)
                .filter_by(
                    provider_name=rec.provider_name,
                    contract_name=rec.contract_name,
                    contract_type=rec.contract_type,
                    commodity=rec.commodity,
                )
                .first()
            )

            if not existing:
                session.add(
                    ScraperProviderContract(
                        provider_name=rec.provider_name,
                        contract_name=rec.contract_name,
                        contract_type=rec.contract_type,
                        commodity=rec.commodity,
                        first_seen_run=run_id,
                        review_status="pending_review",
                    )
                )
                new_count += 1

        if new_count:
            logger.info("new_providers_registered", count=new_count)


def _observation_to_params(rec: PriceObservation, run_id: str) -> dict[str, Any]:
    """Convert a PriceObservation to SQL parameter dict."""
    valid_from = rec.valid_from
    if valid_from and len(valid_from) == 7:
        valid_from = f"{valid_from}-01"

    valid_to = rec.valid_to
    if valid_to and len(valid_to) == 7:
        valid_to = f"{valid_to}-01"

    return {
        "run_id": run_id,
        "content_hash": rec.content_hash,
        "source": rec.source,
        "scraped_at": rec.scraped_at_utc,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "country": rec.country,
        "provider_name": rec.provider_name,
        "contract_name": rec.contract_name,
        "contract_type": rec.contract_type,
        "commodity": rec.commodity,
        "meter_direction": rec.meter_direction,
        "tou": rec.tou,
        "unit": rec.unit,
        "value": rec.value,
        "currency": rec.currency,
        "is_all_in": rec.is_all_in,
        "price_includes": rec.price_includes,
        "notes": rec.notes,
        "source_fields": rec.source_fields,
    }
