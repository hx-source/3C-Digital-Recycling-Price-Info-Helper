from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SourceType(StrEnum):
    EXCEL = "excel"
    IMAGE = "image"


class BatchStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    REVIEW = "review"
    COMMITTED = "committed"
    FAILED = "failed"
    NEEDS_OCR = "needs_ocr"


class PriceStatus(StrEnum):
    QUOTED = "quoted"
    NO_QUOTE = "no_quote"
    MASKED = "masked"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False, default="郑州思物通讯")
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[BatchStatus] = mapped_column(Enum(BatchStatus), nullable=False, default=BatchStatus.UPLOADED)
    quote_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    committed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    candidates: Mapped[list[QuoteCandidate]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )
    quotes: Mapped[list[PriceQuote]] = relationship(back_populates="batch")


class QuoteCandidate(Base):
    __tablename__ = "quote_candidates"
    __table_args__ = (
        Index("ix_candidate_batch_review", "batch_id", "review_status"),
        Index("ix_candidate_identity", "brand", "model_normalized", "storage", "color"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False)
    sheet_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cell_address: Mapped[str | None] = mapped_column(String(40), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Source rectangles are captured while the image OCR result is still in memory.
    # Keeping them on the candidate means opening the original image never needs OCR again.
    source_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_region_precise: Mapped[bool | None] = mapped_column(nullable=True)
    quote_date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="手机")
    brand: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(180), nullable=False)
    model_normalized: Mapped[str] = mapped_column(String(180), nullable=False)
    storage: Mapped[str | None] = mapped_column(String(60), nullable=True)
    color: Mapped[str | None] = mapped_column(String(80), nullable=True)
    variant: Mapped[str | None] = mapped_column(String(120), nullable=True)
    price_status: Mapped[PriceStatus] = mapped_column(Enum(PriceStatus), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.75)
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), nullable=False, default=ReviewStatus.PENDING
    )
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False, default="v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    batch: Mapped[ImportBatch] = relationship(back_populates="candidates")
    quote: Mapped[PriceQuote | None] = relationship(back_populates="candidate", uselist=False)


class PriceQuote(Base):
    __tablename__ = "price_quotes"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_price_quote_candidate"),
        Index("ix_quote_lookup", "model_key", "quote_date"),
        Index("ix_quote_date_brand", "quote_date", "brand"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id"), nullable=False)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("quote_candidates.id"), nullable=False)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    quote_date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    brand: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(180), nullable=False)
    model_normalized: Mapped[str] = mapped_column(String(180), nullable=False)
    storage: Mapped[str | None] = mapped_column(String(60), nullable=True)
    color: Mapped[str | None] = mapped_column(String(80), nullable=True)
    variant: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model_key: Mapped[str] = mapped_column(String(500), nullable=False)
    price_status: Mapped[PriceStatus] = mapped_column(Enum(PriceStatus), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    batch: Mapped[ImportBatch] = relationship(back_populates="quotes")
    candidate: Mapped[QuoteCandidate] = relationship(back_populates="quote")
