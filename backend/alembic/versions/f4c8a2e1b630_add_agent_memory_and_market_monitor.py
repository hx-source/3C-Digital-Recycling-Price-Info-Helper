"""add agent memory and market monitor

Revision ID: f4c8a2e1b630
Revises: e2b7c4d9a015
Create Date: 2026-09-10
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "f4c8a2e1b630"
down_revision: Union[str, None] = "e2b7c4d9a015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.String(36), nullable=False), sa.Column("title", sa.String(120), nullable=False),
        sa.Column("memory", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "agent_conversation_messages",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(20), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=True), sa.Column("tools_used", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["agent_conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_message_conversation_created", "agent_conversation_messages", ["conversation_id", "created_at"])
    monitor_status = sa.Enum("QUEUED", "RUNNING", "COMPLETED", "FAILED", name="monitorrunstatus")
    op.create_table(
        "market_monitor_runs",
        sa.Column("id", sa.String(36), nullable=False), sa.Column("batch_id", sa.Integer(), nullable=True),
        sa.Column("trigger_type", sa.String(20), nullable=False), sa.Column("status", monitor_status, nullable=False),
        sa.Column("quote_date", sa.Date(), nullable=True), sa.Column("previous_date", sa.Date(), nullable=True),
        sa.Column("scanned_quotes", sa.Integer(), nullable=False), sa.Column("finding_count", sa.Integer(), nullable=False),
        sa.Column("danger_count", sa.Integer(), nullable=False), sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True), sa.Column("generated_by_model", sa.Boolean(), nullable=False),
        sa.Column("model_name", sa.String(120), nullable=True), sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True), sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["import_batches.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitor_run_quote_date_created", "market_monitor_runs", ["quote_date", "created_at"])
    op.create_table(
        "market_monitor_findings",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("finding_type", sa.String(40), nullable=False), sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("brand", sa.String(80), nullable=True), sa.Column("model", sa.String(180), nullable=True),
        sa.Column("title", sa.String(255), nullable=False), sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["market_monitor_runs.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitor_finding_run_severity", "market_monitor_findings", ["run_id", "severity"])
    op.create_index("ix_monitor_finding_type", "market_monitor_findings", ["finding_type"])


def downgrade() -> None:
    op.drop_index("ix_monitor_finding_type", table_name="market_monitor_findings")
    op.drop_index("ix_monitor_finding_run_severity", table_name="market_monitor_findings")
    op.drop_table("market_monitor_findings")
    op.drop_index("ix_monitor_run_quote_date_created", table_name="market_monitor_runs")
    op.drop_table("market_monitor_runs")
    op.drop_index("ix_agent_message_conversation_created", table_name="agent_conversation_messages")
    op.drop_table("agent_conversation_messages")
    op.drop_table("agent_conversations")
