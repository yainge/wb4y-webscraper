"""Initial schema: scraper_runs, scraper_price_observations, scraper_provider_contracts + views.

Revision ID: 001
Revises:
Create Date: 2026-02-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # scraper_runs
    op.create_table(
        "scraper_runs",
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("record_count", sa.Integer()),
        sa.Column("raw_snapshot_hash", sa.Text()),
        sa.Column("dashboard_structure", JSONB()),
        sa.Column("drift_report", JSONB()),
        sa.Column("error_message", sa.Text()),
    )

    # scraper_price_observations
    op.create_table(
        "scraper_price_observations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default="tableau_acm_price_monitor"),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(), nullable=False),
        sa.Column("valid_to", sa.DateTime()),
        sa.Column("country", sa.String(), nullable=False, server_default="NL"),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("contract_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("contract_type", sa.String(), nullable=False),
        sa.Column("commodity", sa.String(), nullable=False),
        sa.Column("meter_direction", sa.String(), nullable=False),
        sa.Column("tou", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("value", sa.Numeric(12, 6), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default="EUR"),
        sa.Column("is_all_in", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("price_includes", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("source_fields", JSONB()),
        sa.Column("review_status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_unique_constraint(
        "uq_price_obs_natural_key",
        "scraper_price_observations",
        ["provider_name", "contract_name", "contract_type", "commodity", "meter_direction", "tou", "unit", "valid_from"],
    )
    op.create_index("idx_price_obs_provider", "scraper_price_observations", ["provider_name"])
    op.create_index("idx_price_obs_valid_from", "scraper_price_observations", ["valid_from"])
    op.create_index("idx_price_obs_review", "scraper_price_observations", ["review_status"])
    op.create_index("idx_price_obs_commodity_type", "scraper_price_observations", ["commodity", "contract_type"])

    # scraper_provider_contracts
    op.create_table(
        "scraper_provider_contracts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("contract_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("contract_type", sa.String(), nullable=False),
        sa.Column("commodity", sa.String(), nullable=False),
        sa.Column("first_seen_run", sa.String()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("review_status", sa.String(), nullable=False, server_default="pending_review"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
    )

    op.create_unique_constraint(
        "uq_provider_contract_natural_key",
        "scraper_provider_contracts",
        ["provider_name", "contract_name", "contract_type", "commodity"],
    )

    # Views
    op.execute("""
        CREATE OR REPLACE VIEW scraper_price_observations_monthly AS
        SELECT *,
               date_trunc('month', valid_from)::date AS month
        FROM scraper_price_observations
        WHERE review_status = 'active'
    """)

    op.execute("""
        CREATE OR REPLACE VIEW scraper_wb4u_provider_prices AS
        WITH latest AS (
            SELECT DISTINCT ON (provider_name, contract_type)
                   provider_name, contract_name, contract_type, valid_from
            FROM scraper_price_observations
            WHERE review_status = 'active'
            ORDER BY provider_name, contract_type, valid_from DESC
        ),
        pivoted AS (
            SELECT
                l.provider_name AS "Company name",
                initcap(l.contract_type) AS "Contract type",
                MAX(CASE WHEN t.commodity='electricity' AND t.meter_direction='consumption'
                          AND t.unit='eur_per_kwh' THEN t.value END) AS "Electricity price",
                MAX(CASE WHEN t.commodity='electricity' AND t.unit='eur_per_month'
                          AND t.meter_direction='consumption' THEN t.value END) AS "Monthly Cost",
                MAX(CASE WHEN t.meter_direction='feed_in' AND t.commodity='electricity'
                          AND t.unit='eur_per_kwh' THEN 'yes' END) AS "Feed in specific",
                MAX(CASE WHEN t.meter_direction='feed_in' AND t.commodity='electricity'
                          AND t.unit='eur_per_kwh' THEN t.value END) AS "Feed-in",
                MAX(CASE WHEN t.commodity='gas' AND t.unit='eur_per_m3'
                          THEN t.value END) AS "Gas price",
                MAX(CASE WHEN t.commodity='gas' AND t.unit='eur_per_month'
                          THEN t.value END) AS "Monthly gas cost"
            FROM latest l
            JOIN scraper_price_observations t
              ON t.provider_name = l.provider_name
             AND t.contract_type = l.contract_type
             AND t.valid_from = l.valid_from
             AND t.review_status = 'active'
            GROUP BY l.provider_name, l.contract_type, l.contract_name
        )
        SELECT * FROM pivoted
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS scraper_wb4u_provider_prices")
    op.execute("DROP VIEW IF EXISTS scraper_price_observations_monthly")
    op.drop_table("scraper_provider_contracts")
    op.drop_table("scraper_price_observations")
    op.drop_table("scraper_runs")
