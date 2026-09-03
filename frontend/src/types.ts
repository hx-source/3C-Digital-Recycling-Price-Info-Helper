export type BatchStatus = 'uploaded' | 'parsing' | 'review' | 'committed' | 'failed' | 'needs_ocr'
export type PriceStatus = 'quoted' | 'no_quote' | 'masked'
export type ReviewStatus = 'pending' | 'approved' | 'rejected'

export interface Batch {
  id: number
  source_type: 'excel' | 'image'
  source_name: string
  filename: string
  status: BatchStatus
  quote_date: string | null
  total_candidates: number
  valid_candidates: number
  error_message: string | null
  created_at: string
  committed_at: string | null
}

export interface Candidate {
  id: number
  batch_id: number
  sheet_name: string | null
  cell_address: string | null
  raw_text: string
  source_line: number | null
  quote_date: string
  category: string
  brand: string
  model: string
  model_normalized: string
  storage: string | null
  color: string | null
  variant: string | null
  price_status: PriceStatus
  price: number | null
  confidence: number
  review_status: ReviewStatus
  review_note: string | null
}

export interface CandidatePage {
  items: Candidate[]
  total: number
  page: number
  page_size: number
  summary: CandidateFilterSummary
}

export interface ImageSourceRegion {
  x: number
  y: number
  width: number
  height: number
  image_width: number
  image_height: number
  precise: boolean
}

export interface ExcelSourceCell {
  coordinate: string
  value: string | null
  merged_range: string | null
  is_source: boolean
  is_price: boolean
}

export interface ExcelSourceRow {
  row: number
  cells: ExcelSourceCell[]
}

export interface ExcelSourceContext {
  sheet_name: string
  source_cell: string
  price_cell: string | null
  columns: string[]
  rows: ExcelSourceRow[]
}

export interface CandidateSourcePreview {
  source_type: 'excel' | 'image'
  filename: string
  sheet_name: string | null
  cell_address: string | null
  raw_text: string
  image_url: string | null
  region: ImageSourceRegion | null
  excel_context: ExcelSourceContext | null
  message: string | null
}

export interface CandidateFilterSummary {
  all: number
  pending: number
  low_confidence: number
  incomplete: number
  approved: number
  rejected: number
  merged_source_groups: number
}

export interface ExcelPrecheckIssue {
  reasons: string[]
  sheet_name: string | null
  cell_address: string | null
  brand: string
  model: string
  storage: string | null
  color: string | null
  price_status: PriceStatus
  price: number | null
  previous_price: number | null
  difference: number | null
  raw_text: string
  duplicate_detail: string | null
}

export interface ExcelPrecheckResult {
  total_candidates: number
  normal_candidates: number
  needs_review_candidates: number
  incomplete_candidates: number
  no_quote_candidates: number
  masked_candidates: number
  duplicate_candidates: number
  abnormal_price_candidates: number
  issues: ExcelPrecheckIssue[]
  records: ExcelPrecheckIssue[]
}

export interface Quote {
  id: number
  batch_id: number
  quote_date: string
  source_name: string
  category: string
  brand: string
  model: string
  storage: string | null
  color: string | null
  variant: string | null
  price_status: PriceStatus
  price: number | null
}

export interface PriceChange {
  model_key: string
  brand: string
  model: string
  storage: string | null
  color: string | null
  variant: string | null
  current_date: string
  current_price: number
  previous_date: string | null
  previous_price: number | null
  change_amount: number | null
  change_percent: number | null
  requires_review: boolean
}

export interface DashboardSummary {
  latest_quote_date: string | null
  published_quotes: number
  pending_candidates: number
  today_increases: number
  today_decreases: number
  today_unchanged: number
  top_increases: PriceChange[]
  top_decreases: PriceChange[]
}

export interface AgentMessageInput {
  role: 'user' | 'assistant'
  content: string
}

export interface AgentSource {
  label: string
  detail: string
}

export interface AgentChatResponse {
  answer: string
  sources: AgentSource[]
  tools_used: string[]
  model: string
}

export interface ImportAgentSummaryRequest {
  filename: string
  source_type: 'excel' | 'image' | 'mixed'
  total_candidates: number
  normal_candidates?: number
  needs_review_candidates?: number
  duplicate_candidates?: number
  abnormal_price_candidates?: number
  incomplete_candidates?: number
  no_quote_candidates?: number
  masked_candidates?: number
}

export interface ImportAgentSummaryResponse {
  summary: string
  recommendations: string[]
  generated_by_model: boolean
  model: string
}
