"""add price forecasts and external signals

Revision ID: c3f7a0b4e126
Revises: b2e6f9a3d015
Create Date: 2026-09-11
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c3f7a0b4e126"
down_revision: Union[str, None] = "b2e6f9a3d015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "price_forecasts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_key", sa.String(500), nullable=False),
        sa.Column("brand", sa.String(80), nullable=False),
        sa.Column("model", sa.String(180), nullable=False),
        sa.Column("storage", sa.String(60), nullable=True),
        sa.Column("color", sa.String(80), nullable=True),
        sa.Column("variant", sa.String(120), nullable=True),
        sa.Column("base_date", sa.Date(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("base_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("predicted_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("lower_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("upper_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("up_probability", sa.Float(), nullable=False),
        sa.Column("stable_probability", sa.Float(), nullable=False),
        sa.Column("down_probability", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(80), nullable=False),
        sa.Column("external_score", sa.Float(), nullable=False),
        sa.Column("external_signal_count", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("factors", sa.JSON(), nullable=False),
        sa.Column("actual_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("absolute_error", sa.Numeric(12, 2), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_key", "base_date", "horizon_days", name="uq_forecast_spec_base_horizon"),
    )
    op.create_index("ix_forecast_target_date", "price_forecasts", ["target_date"])
    op.create_index("ix_forecast_spec_created", "price_forecasts", ["model_key", "created_at"])
    op.create_table(
        "external_market_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("query", sa.String(255), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_domain", sa.String(255), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("impact_score", sa.Float(), nullable=True),
        sa.Column("collected_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url_hash", name="uq_external_signal_url_hash"),
    )
    op.create_index("ix_external_signal_query_collected", "external_market_signals", ["query", "collected_at"])


def downgrade() -> None:
    op.drop_index("ix_external_signal_query_collected", table_name="external_market_signals")
    op.drop_table("external_market_signals")
    op.drop_index("ix_forecast_spec_created", table_name="price_forecasts")
    op.drop_index("ix_forecast_target_date", table_name="price_forecasts")
    op.drop_table("price_forecasts")
