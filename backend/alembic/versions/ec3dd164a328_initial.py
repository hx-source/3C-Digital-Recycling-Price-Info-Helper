"""initial schema

Revision ID: ec3dd164a328
Revises:
Create Date: 2026-08-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ec3dd164a328"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.Enum("EXCEL", "IMAGE", name="sourcetype"), nullable=False),
        sa.Column("source_name", sa.String(length=120), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("stored_path", sa.String(length=500), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("UPLOADED", "PARSING", "REVIEW", "COMMITTED", "FAILED", "NEEDS_OCR", name="batchstatus"),
            nullable=False,
        ),
        sa.Column("quote_date", sa.Date(), nullable=True),
        sa.Column("total_candidates", sa.Integer(), nullable=False),
        sa.Column("valid_candidates", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("committed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_batches_file_sha256", "import_batches", ["file_sha256"], unique=False)

    op.create_table(
        "quote_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("sheet_name", sa.String(length=120), nullable=True),
        sa.Column("cell_address", sa.String(length=40), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("source_line", sa.Integer(), nullable=True),
        sa.Column("quote_date", sa.Date(), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("brand", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=180), nullable=False),
        sa.Column("model_normalized", sa.String(length=180), nullable=False),
        sa.Column("storage", sa.String(length=60), nullable=True),
        sa.Column("color", sa.String(length=80), nullable=True),
        sa.Column("variant", sa.String(length=120), nullable=True),
        sa.Column("price_status", sa.Enum("QUOTED", "NO_QUOTE", "MASKED", name="pricestatus"), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("review_status", sa.Enum("PENDING", "APPROVED", "REJECTED", name="reviewstatus"), nullable=False),
        sa.Column("review_note", sa.String(length=500), nullable=True),
        sa.Column("parser_version", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["import_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_batch_review", "quote_candidates", ["batch_id", "review_status"], unique=False)
    op.create_index("ix_candidate_identity", "quote_candidates", ["brand", "model_normalized", "storage", "color"], unique=False)

    op.create_table(
        "price_quotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("source_name", sa.String(length=120), nullable=False),
        sa.Column("quote_date", sa.Date(), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("brand", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=180), nullable=False),
        sa.Column("model_normalized", sa.String(length=180), nullable=False),
        sa.Column("storage", sa.String(length=60), nullable=True),
        sa.Column("color", sa.String(length=80), nullable=True),
        sa.Column("variant", sa.String(length=120), nullable=True),
        sa.Column("model_key", sa.String(length=500), nullable=False),
        sa.Column("price_status", sa.Enum("QUOTED", "NO_QUOTE", "MASKED", name="pricestatus"), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["import_batches.id"]),
        sa.ForeignKeyConstraint(["candidate_id"], ["quote_candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", name="uq_price_quote_candidate"),
    )
    op.create_index("ix_quote_date_brand", "price_quotes", ["quote_date", "brand"], unique=False)
    op.create_index("ix_quote_lookup", "price_quotes", ["model_key", "quote_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_quote_lookup", table_name="price_quotes")
    op.drop_index("ix_quote_date_brand", table_name="price_quotes")
    op.drop_table("price_quotes")
    op.drop_index("ix_candidate_identity", table_name="quote_candidates")
    op.drop_index("ix_candidate_batch_review", table_name="quote_candidates")
    op.drop_table("quote_candidates")
    op.drop_index("ix_import_batches_file_sha256", table_name="import_batches")
    op.drop_table("import_batches")

