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
    JSON,
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


class ImportTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"


class ImportTaskItemStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReviewSampleStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class MonitorRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ImportTask(Base):
    __tablename__ = "import_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[ImportTaskStatus] = mapped_column(
        Enum(ImportTaskStatus), nullable=False, default=ImportTaskStatus.QUEUED
    )
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    quote_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    excel_import_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="all")
    manual_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    items: Mapped[list[ImportTaskItem]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="ImportTaskItem.position"
    )


class ImportTaskItem(Base):
    __tablename__ = "import_task_items"
    __table_args__ = (Index("ix_import_task_item_task_position", "task_id", "position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("import_tasks.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ImportTaskItemStatus] = mapped_column(
        Enum(ImportTaskItemStatus), nullable=False, default=ImportTaskItemStatus.QUEUED
    )
    stage: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    candidate_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    task: Mapped[ImportTask] = relationship(back_populates="items")


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


class ReviewAuditLog(Base):
    __tablename__ = "review_audit_logs"
    __table_args__ = (
        Index("ix_review_audit_batch_created", "batch_id", "created_at"),
        Index("ix_review_audit_candidate_created", "candidate_id", "created_at"),
        Index("ix_review_audit_action_created", "action_type", "created_at"),
        Index("ix_review_audit_agent_run", "agent_run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("quote_candidates.id", ondelete="SET NULL"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    operator_type: Mapped[str] = mapped_column(String(20), nullable=False)
    before_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    changed_fields: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    agent_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    rule_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class ReviewSample(Base):
    __tablename__ = "review_samples"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_review_sample_candidate"),
        Index("ix_review_sample_batch_status", "batch_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("quote_candidates.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[ReviewSampleStatus] = mapped_column(
        Enum(ReviewSampleStatus), nullable=False, default=ReviewSampleStatus.PENDING
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    candidate: Mapped[QuoteCandidate] = relationship()


class AgentConversation(Base):
    __tablename__ = "agent_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="新行情问答")
    memory: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list[AgentConversationMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="AgentConversationMessage.id"
    )


class AgentConversationMessage(Base):
    __tablename__ = "agent_conversation_messages"
    __table_args__ = (Index("ix_agent_message_conversation_created", "conversation_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tools_used: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    conversation: Mapped[AgentConversation] = relationship(back_populates="messages")


class MarketMonitorRun(Base):
    __tablename__ = "market_monitor_runs"
    __table_args__ = (Index("ix_monitor_run_quote_date_created", "quote_date", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[MonitorRunStatus] = mapped_column(
        Enum(MonitorRunStatus), nullable=False, default=MonitorRunStatus.QUEUED
    )
    quote_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    previous_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    scanned_quotes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    finding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    danger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_by_model: Mapped[bool] = mapped_column(nullable=False, default=False)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    findings: Mapped[list[MarketMonitorFinding]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="MarketMonitorFinding.id"
    )


class MarketMonitorFinding(Base):
    __tablename__ = "market_monitor_findings"
    __table_args__ = (
        Index("ix_monitor_finding_run_severity", "run_id", "severity"),
        Index("ix_monitor_finding_type", "finding_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("market_monitor_runs.id", ondelete="CASCADE"), nullable=False
    )
    finding_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(180), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    quote_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_quotes.id", ondelete="SET NULL"), nullable=True
    )
    handling_status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    diagnosis: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    proposed_price_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    diagnosis_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    diagnosis_generated_by_model: Mapped[bool] = mapped_column(nullable=False, default=False)
    diagnosis_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    diagnosis_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    handled_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    run: Mapped[MarketMonitorRun] = relationship(back_populates="findings")
