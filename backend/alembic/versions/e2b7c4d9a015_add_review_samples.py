"""add automatic approval review samples

Revision ID: e2b7c4d9a015
Revises: d9f0a3b7c812
Create Date: 2026-09-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2b7c4d9a015"
down_revision: Union[str, None] = "d9f0a3b7c812"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    sample_status = sa.Enum("PENDING", "PASSED", "FAILED", name="reviewsamplestatus")
    op.create_table(
        "review_samples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("status", sample_status, nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("sampled_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["import_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["quote_candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", name="uq_review_sample_candidate"),
    )
    op.create_index("ix_review_sample_batch_status", "review_samples", ["batch_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_review_sample_batch_status", table_name="review_samples")
    op.drop_table("review_samples")
