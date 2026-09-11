"""add immutable review audit logs

Revision ID: c7a9d8e6f421
Revises: b41c0b3f701
Create Date: 2026-09-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7a9d8e6f421"
down_revision: Union[str, None] = "b41c0b3f701"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=True),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("action_type", sa.String(length=40), nullable=False),
        sa.Column("operator_type", sa.String(length=20), nullable=False),
        sa.Column("before_data", sa.JSON(), nullable=True),
        sa.Column("after_data", sa.JSON(), nullable=True),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("agent_run_id", sa.String(length=64), nullable=True),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("rule_version", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["import_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["candidate_id"], ["quote_candidates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_audit_action_created", "review_audit_logs", ["action_type", "created_at"])
    op.create_index("ix_review_audit_agent_run", "review_audit_logs", ["agent_run_id"])
    op.create_index("ix_review_audit_batch_created", "review_audit_logs", ["batch_id", "created_at"])
    op.create_index("ix_review_audit_candidate_created", "review_audit_logs", ["candidate_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_review_audit_candidate_created", table_name="review_audit_logs")
    op.drop_index("ix_review_audit_batch_created", table_name="review_audit_logs")
    op.drop_index("ix_review_audit_agent_run", table_name="review_audit_logs")
    op.drop_index("ix_review_audit_action_created", table_name="review_audit_logs")
    op.drop_table("review_audit_logs")
