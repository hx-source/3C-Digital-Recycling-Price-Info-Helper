"""add persistent import background tasks

Revision ID: d9f0a3b7c812
Revises: c7a9d8e6f421
Create Date: 2026-09-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d9f0a3b7c812"
down_revision: Union[str, None] = "c7a9d8e6f421"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    task_status = sa.Enum("QUEUED", "RUNNING", "COMPLETED", "PARTIAL_FAILED", "FAILED", name="importtaskstatus")
    item_status = sa.Enum("QUEUED", "PROCESSING", "COMPLETED", "FAILED", name="importtaskitemstatus")
    op.create_table(
        "import_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("status", task_status, nullable=False),
        sa.Column("source_name", sa.String(length=120), nullable=False),
        sa.Column("quote_date", sa.Date(), nullable=True),
        sa.Column("excel_import_mode", sa.String(length=20), nullable=False),
        sa.Column("manual_text", sa.Text(), nullable=True),
        sa.Column("total_files", sa.Integer(), nullable=False),
        sa.Column("completed_files", sa.Integer(), nullable=False),
        sa.Column("succeeded_files", sa.Integer(), nullable=False),
        sa.Column("failed_files", sa.Integer(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("current_filename", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "import_task_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("stored_path", sa.String(length=500), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", item_status, nullable=False),
        sa.Column("stage", sa.String(length=30), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["import_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["import_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_task_item_task_position", "import_task_items", ["task_id", "position"])


def downgrade() -> None:
    op.drop_index("ix_import_task_item_task_position", table_name="import_task_items")
    op.drop_table("import_task_items")
    op.drop_table("import_tasks")
