from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.entities import BatchStatus, ImportTaskItemStatus, ImportTaskStatus, PriceStatus, ReviewSampleStatus, ReviewStatus, SourceType


class ImportTaskItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    filename: str
    status: ImportTaskItemStatus
    stage: str
    progress: int
    batch_id: int | None
    candidate_count: int | None
    error_message: str | None


class ImportTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: ImportTaskStatus
    total_files: int
    completed_files: int
    succeeded_files: int
    failed_files: int
    progress: int
    current_filename: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    items: list[ImportTaskItemRead]


class BatchSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_type: SourceType
    source_name: str
    filename: str
    status: BatchStatus
    quote_date: date | None
    total_candidates: int
    valid_candidates: int
    error_message: str | None
    created_at: datetime
    committed_at: datetime | None


class CandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int
    sheet_name: str | None
    cell_address: str | None
    raw_text: str
    source_line: int | None
    quote_date: date
    category: str
    brand: str
    model: str
    model_normalized: str
    storage: str | None
    color: str | None
    variant: str | None
    price_status: PriceStatus
    price: Decimal | None
    confidence: float
    review_status: ReviewStatus
    review_note: str | None


class ImageSourceRegionRead(BaseModel):
    x: int
    y: int
    width: int
    height: int
    image_width: int
    image_height: int
    precise: bool


class ExcelSourceCellRead(BaseModel):
    coordinate: str
    value: str | None
    merged_range: str | None = None
    is_source: bool = False
    is_price: bool = False


class ExcelSourceRowRead(BaseModel):
    row: int
    cells: list[ExcelSourceCellRead]


class ExcelSourceContextRead(BaseModel):
    sheet_name: str
    source_cell: str
    price_cell: str | None = None
    columns: list[str]
    rows: list[ExcelSourceRowRead]


class CandidateSourcePreview(BaseModel):
    source_type: SourceType
    filename: str
    sheet_name: str | None
    cell_address: str | None
    raw_text: str
    image_url: str | None = None
    region: ImageSourceRegionRead | None = None
    excel_context: ExcelSourceContextRead | None = None
    message: str | None = None


class CandidateFilterSummary(BaseModel):
    all: int
    pending: int
    low_confidence: int
    incomplete: int
    approved: int
    auto_approved: int = 0
    rejected: int
    merged_source_groups: int = 0


class CandidatePage(BaseModel):
    items: list[CandidateRead]
    total: int
    page: int
    page_size: int
    summary: CandidateFilterSummary


class ReviewAuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int | None
    candidate_id: int | None
    action_type: str
    operator_type: str
    before_data: dict | None
    after_data: dict | None
    changed_fields: list[str] = Field(default_factory=list)
    reason: str | None
    agent_run_id: str | None
    model_name: str | None
    rule_version: str | None
    created_at: datetime


class CandidateUpdate(BaseModel):
    quote_date: date | None = None
    category: str | None = Field(default=None, max_length=80)
    brand: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=180)
    storage: str | None = Field(default=None, max_length=60)
    color: str | None = Field(default=None, max_length=80)
    variant: str | None = Field(default=None, max_length=120)
    price_status: PriceStatus | None = None
    price: Decimal | None = Field(default=None, ge=0)
    review_status: ReviewStatus | None = None
    review_note: str | None = Field(default=None, max_length=500)


class SourceLineReparseRequest(BaseModel):
    raw_text: str = Field(min_length=3, max_length=2000)


class SourceGroupCandidateInput(CandidateUpdate):
    id: int | None = None


class SourceGroupReplaceRequest(BaseModel):
    items: list[SourceGroupCandidateInput] = Field(min_length=1, max_length=80)


class BatchQuoteDateUpdate(BaseModel):
    quote_date: date


class ExcelPrecheckIssue(BaseModel):
    reasons: list[str]
    sheet_name: str | None = None
    cell_address: str | None = None
    brand: str
    model: str
    storage: str | None = None
    color: str | None = None
    price_status: PriceStatus
    price: Decimal | None = None
    previous_price: Decimal | None = None
    difference: Decimal | None = None
    raw_text: str
    duplicate_detail: str | None = None


class ExcelPrecheckResult(BaseModel):
    total_candidates: int
    normal_candidates: int
    needs_review_candidates: int
    incomplete_candidates: int
    no_quote_candidates: int
    masked_candidates: int
    duplicate_candidates: int
    abnormal_price_candidates: int
    issues: list[ExcelPrecheckIssue]
    records: list[ExcelPrecheckIssue]


class PurgeAllDataRequest(BaseModel):
    """Explicit confirmation required before destructive workspace-wide cleanup."""

    confirmation: str = Field(min_length=1, max_length=40)


class BulkReviewRequest(BaseModel):
    candidate_ids: list[int] = Field(min_length=1)
    review_status: ReviewStatus


class CommitResult(BaseModel):
    batch_id: int
    inserted: int
    skipped: int
    status: BatchStatus


class QuoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int
    quote_date: date
    source_name: str
    category: str
    brand: str
    model: str
    storage: str | None
    color: str | None
    variant: str | None
    price_status: PriceStatus
    price: Decimal | None


class QuotePage(BaseModel):
    items: list[QuoteRead]
    total: int
    page: int
    page_size: int


class PriceChangeRead(BaseModel):
    model_key: str
    brand: str
    model: str
    storage: str | None
    color: str | None
    variant: str | None
    current_date: date
    current_price: Decimal
    previous_date: date | None
    previous_price: Decimal | None
    change_amount: Decimal | None
    change_percent: float | None
    requires_review: bool = False


class TrendPoint(BaseModel):
    quote_date: date
    price: Decimal


class DashboardSummary(BaseModel):
    latest_quote_date: date | None
    published_quotes: int
    pending_candidates: int
    today_increases: int
    today_decreases: int
    today_unchanged: int
    top_increases: list[PriceChangeRead]
    top_decreases: list[PriceChangeRead]


class AgentMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class AgentChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[AgentMessage] = Field(default_factory=list, max_length=12)
    conversation_id: str | None = Field(default=None, min_length=36, max_length=36)


class AgentSource(BaseModel):
    label: str
    detail: str


class AgentChatResponse(BaseModel):
    answer: str
    sources: list[AgentSource] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    model: str
    conversation_id: str
    memory: dict = Field(default_factory=dict)


class AgentConversationMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    sources: list[AgentSource] | None
    tools_used: list[str] | None
    created_at: datetime


class AgentConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    memory: dict
    created_at: datetime
    updated_at: datetime
    messages: list[AgentConversationMessageRead] = Field(default_factory=list)


class MarketMonitorFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    finding_type: str
    severity: str
    brand: str | None
    model: str | None
    title: str
    detail: str
    evidence: dict | None
    quote_id: int | None
    handling_status: str
    diagnosis: str | None
    recommendation: str | None
    proposed_price: Decimal | None
    proposed_price_status: str | None
    diagnosis_confidence: float | None
    diagnosis_generated_by_model: bool
    diagnosis_model: str | None
    diagnosis_run_id: str | None
    handled_reason: str | None
    handled_at: datetime | None
    created_at: datetime


class MarketFindingActionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class MarketFindingApplyRequest(BaseModel):
    proposed_price: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    proposed_price_status: Literal["quoted", "masked", "no_quote"] | None = None
    reason: str | None = Field(default=None, max_length=500)


class MarketMonitorRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    batch_id: int | None
    trigger_type: str
    status: str
    quote_date: date | None
    previous_date: date | None
    scanned_quotes: int
    finding_count: int
    danger_count: int
    warning_count: int
    summary: str | None
    generated_by_model: bool
    model_name: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    findings: list[MarketMonitorFindingRead] = Field(default_factory=list)


class ImportAgentSummaryRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    source_type: str = Field(pattern="^(excel|image|mixed)$")
    total_candidates: int = Field(ge=0)
    normal_candidates: int = Field(default=0, ge=0)
    needs_review_candidates: int = Field(default=0, ge=0)
    duplicate_candidates: int = Field(default=0, ge=0)
    abnormal_price_candidates: int = Field(default=0, ge=0)
    incomplete_candidates: int = Field(default=0, ge=0)
    no_quote_candidates: int = Field(default=0, ge=0)
    masked_candidates: int = Field(default=0, ge=0)


class ImportAgentSummaryResponse(BaseModel):
    summary: str
    recommendations: list[str] = Field(default_factory=list)
    generated_by_model: bool
    model: str


ReviewDiagnosisField = Literal[
    "brand",
    "model",
    "storage",
    "color",
    "variant",
    "price_status",
    "price",
    "review_status",
]


class ReviewDiagnosisEvidence(BaseModel):
    category: Literal["source", "history", "duplicate", "structure", "confidence"]
    title: str
    detail: str
    severity: Literal["info", "warning", "danger"] = "info"


class ReviewDiagnosisChange(BaseModel):
    field: ReviewDiagnosisField
    label: str
    current_value: str | Decimal | None = None
    suggested_value: str | Decimal | None = None
    reason: str


class ReviewAgentStep(BaseModel):
    order: int
    phase: Literal["planning", "tool", "reasoning", "verification"]
    title: str
    detail: str
    status: Literal["completed", "fallback"] = "completed"
    tool: str | None = None


class ReviewDiagnosisResponse(BaseModel):
    agent_run_id: str
    candidate_id: int
    candidate_signature: str
    severity: Literal["normal", "warning", "danger"]
    issue_types: list[str] = Field(default_factory=list)
    summary: str
    evidence: list[ReviewDiagnosisEvidence] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    proposed_changes: list[ReviewDiagnosisChange] = Field(default_factory=list)
    requires_confirmation: bool = True
    generated_by_model: bool
    model: str
    source_type: SourceType
    source_label: str
    recognition_confidence: float
    verification_status: Literal["unverified", "human_confirmed"]
    agent_mode: Literal["tool_calling", "rule_fallback"]
    tools_used: list[str] = Field(default_factory=list)
    workflow_steps: list[ReviewAgentStep] = Field(default_factory=list)


class ReviewDiagnosisApplyRequest(BaseModel):
    candidate_signature: str = Field(min_length=64, max_length=64)
    decision: Literal["apply_suggestions", "mark_no_issue"]
    fields: list[ReviewDiagnosisField] = Field(default_factory=list, max_length=8)
    agent_run_id: str | None = Field(default=None, max_length=64)


class ReviewDiagnosisApplyResponse(BaseModel):
    candidate: CandidateRead
    applied_fields: list[str] = Field(default_factory=list)
    remaining_issue_types: list[str] = Field(default_factory=list)
    verification_summary: str


class ReviewBatchDiagnosisItem(BaseModel):
    candidate: CandidateRead
    severity: Literal["warning", "danger"]
    issue_types: list[str] = Field(default_factory=list)
    summary: str
    source_label: str


class ReviewBatchDiagnosisResponse(BaseModel):
    batch_id: int
    batch_signature: str
    scanned_count: int
    safe_count: int
    pending_safe_count: int
    auto_approved_count: int = 0
    warning_count: int
    danger_count: int
    issue_counts: dict[str, int] = Field(default_factory=dict)
    risks: list[ReviewBatchDiagnosisItem] = Field(default_factory=list)


class ReviewBatchApproveSafeRequest(BaseModel):
    batch_signature: str = Field(min_length=64, max_length=64)


class ReviewBatchApproveSafeResponse(BaseModel):
    batch_id: int
    approved_count: int
    remaining_pending: int
    agent_run_id: str


class ReviewSampleCreateRequest(BaseModel):
    count: int | None = Field(default=None, ge=1, le=100)


class ReviewSampleDecisionRequest(BaseModel):
    decision: Literal["passed", "failed"]
    note: str | None = Field(default=None, max_length=500)


class ReviewSampleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int
    candidate_id: int
    status: ReviewSampleStatus
    note: str | None
    sampled_at: datetime
    reviewed_at: datetime | None
    candidate: CandidateRead


class ReviewSampleQueueResponse(BaseModel):
    batch_id: int
    requested_count: int
    created_count: int
    eligible_count: int
    items: list[ReviewSampleRead] = Field(default_factory=list)


class ReviewQualityStatsResponse(BaseModel):
    batch_id: int
    auto_approved_total: int
    currently_auto_approved: int
    sampled_total: int
    sampled_pending: int
    sampled_passed: int
    sampled_failed: int
    revoked_total: int
    sample_coverage_percent: float
    verified_accuracy_percent: float | None
