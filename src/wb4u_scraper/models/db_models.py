from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class ScraperRun(Base):
    __tablename__ = "scraper_runs"

    run_id = Column(String, primary_key=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    finished_at = Column(DateTime(timezone=True))
    status = Column(String, nullable=False, server_default="running")
    source_url = Column(Text, nullable=False)
    record_count = Column(Integer)
    raw_snapshot_hash = Column(Text)
    dashboard_structure = Column(JSONB)
    drift_report = Column(JSONB)
    error_message = Column(Text)


class ScraperPriceObservation(Base):
    __tablename__ = "scraper_price_observations"
    __table_args__ = (
        UniqueConstraint(
            "provider_name",
            "contract_name",
            "contract_type",
            "commodity",
            "meter_direction",
            "tou",
            "unit",
            "valid_from",
            name="uq_price_obs_natural_key",
        ),
        Index("idx_price_obs_provider", "provider_name"),
        Index("idx_price_obs_valid_from", "valid_from"),
        Index("idx_price_obs_review", "review_status"),
        Index("idx_price_obs_commodity_type", "commodity", "contract_type"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(String, nullable=False)
    content_hash = Column(Text, nullable=False)
    source = Column(Text, nullable=False, server_default="tableau_acm_price_monitor")
    scraped_at = Column(DateTime(timezone=True), nullable=False)
    valid_from = Column(DateTime, nullable=False)
    valid_to = Column(DateTime)
    country = Column(String, nullable=False, server_default="NL")
    provider_name = Column(Text, nullable=False)
    contract_name = Column(Text, nullable=False, server_default="")
    contract_type = Column(String, nullable=False)
    commodity = Column(String, nullable=False)
    meter_direction = Column(String, nullable=False)
    tou = Column(String, nullable=False)
    unit = Column(String, nullable=False)
    value = Column(Numeric(12, 6), nullable=False)
    currency = Column(String, nullable=False, server_default="EUR")
    is_all_in = Column(Boolean, nullable=False, server_default="true")
    price_includes = Column(Text)
    notes = Column(Text)
    source_fields = Column(JSONB)
    review_status = Column(String, nullable=False, server_default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class ScraperProviderContract(Base):
    __tablename__ = "scraper_provider_contracts"
    __table_args__ = (
        UniqueConstraint(
            "provider_name",
            "contract_name",
            "contract_type",
            "commodity",
            name="uq_provider_contract_natural_key",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    provider_name = Column(Text, nullable=False)
    contract_name = Column(Text, nullable=False, server_default="")
    contract_type = Column(String, nullable=False)
    commodity = Column(String, nullable=False)
    first_seen_run = Column(String)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    review_status = Column(String, nullable=False, server_default="pending_review")
    reviewed_at = Column(DateTime(timezone=True))
    notes = Column(Text)
