"""add remediation price status

Revision ID: b2e6f9a3d015
Revises: a1d5e8f2c904
Create Date: 2026-09-10
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "b2e6f9a3d015"
down_revision: Union[str, None] = "a1d5e8f2c904"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("market_monitor_findings", sa.Column("proposed_price_status", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("market_monitor_findings", "proposed_price_status")
