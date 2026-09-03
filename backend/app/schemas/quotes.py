from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.entities import BatchStatus, PriceStatus, ReviewStatus, SourceType


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
    rejected: int
    merged_source_groups: int = 0


class CandidatePage(BaseModel):
    items: list[CandidateRead]
    total: int
    page: int
    page_size: int
    summary: CandidateFilterSummary


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


class AgentSource(BaseModel):
    label: str
    detail: str


class AgentChatResponse(BaseModel):
    answer: str
    sources: list[AgentSource] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    model: str


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
