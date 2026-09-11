"""add monitor finding remediation

Revision ID: a1d5e8f2c904
Revises: f4c8a2e1b630
Create Date: 2026-09-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1d5e8f2c904"
down_revision: Union[str, None] = "f4c8a2e1b630"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("market_monitor_findings", sa.Column("quote_id", sa.Integer(), nullable=True))
    op.add_column("market_monitor_findings", sa.Column("handling_status", sa.String(20), nullable=False, server_default="open"))
    op.add_column("market_monitor_findings", sa.Column("diagnosis", sa.Text(), nullable=True))
    op.add_column("market_monitor_findings", sa.Column("recommendation", sa.Text(), nullable=True))
    op.add_column("market_monitor_findings", sa.Column("proposed_price", sa.Numeric(12, 2), nullable=True))
    op.add_column("market_monitor_findings", sa.Column("diagnosis_confidence", sa.Float(), nullable=True))
    op.add_column("market_monitor_findings", sa.Column("diagnosis_generated_by_model", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("market_monitor_findings", sa.Column("diagnosis_model", sa.String(120), nullable=True))
    op.add_column("market_monitor_findings", sa.Column("diagnosis_run_id", sa.String(64), nullable=True))
    op.add_column("market_monitor_findings", sa.Column("handled_reason", sa.String(500), nullable=True))
    op.add_column("market_monitor_findings", sa.Column("handled_at", sa.DateTime(), nullable=True))
    op.create_foreign_key("fk_monitor_finding_quote", "market_monitor_findings", "price_quotes", ["quote_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_monitor_finding_handling_status", "market_monitor_findings", ["handling_status"])


def downgrade() -> None:
    op.drop_index("ix_monitor_finding_handling_status", table_name="market_monitor_findings")
    op.drop_constraint("fk_monitor_finding_quote", "market_monitor_findings", type_="foreignkey")
    for column in (
        "handled_at", "handled_reason", "diagnosis_run_id", "diagnosis_model",
        "diagnosis_generated_by_model", "diagnosis_confidence", "proposed_price",
        "recommendation", "diagnosis", "handling_status", "quote_id",
    ):
        op.drop_column("market_monitor_findings", column)
