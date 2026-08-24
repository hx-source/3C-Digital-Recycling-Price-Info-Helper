"""cache image source regions on quote candidates

Revision ID: b41c0b3f701
Revises: ec3dd164a328
Create Date: 2026-08-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b41c0b3f701"
down_revision: Union[str, None] = "ec3dd164a328"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("quote_candidates", sa.Column("source_x", sa.Integer(), nullable=True))
    op.add_column("quote_candidates", sa.Column("source_y", sa.Integer(), nullable=True))
    op.add_column("quote_candidates", sa.Column("source_width", sa.Integer(), nullable=True))
    op.add_column("quote_candidates", sa.Column("source_height", sa.Integer(), nullable=True))
    op.add_column("quote_candidates", sa.Column("source_image_width", sa.Integer(), nullable=True))
    op.add_column("quote_candidates", sa.Column("source_image_height", sa.Integer(), nullable=True))
    op.add_column("quote_candidates", sa.Column("source_region_precise", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("quote_candidates", "source_region_precise")
    op.drop_column("quote_candidates", "source_image_height")
    op.drop_column("quote_candidates", "source_image_width")
    op.drop_column("quote_candidates", "source_height")
    op.drop_column("quote_candidates", "source_width")
    op.drop_column("quote_candidates", "source_y")
    op.drop_column("quote_candidates", "source_x")
