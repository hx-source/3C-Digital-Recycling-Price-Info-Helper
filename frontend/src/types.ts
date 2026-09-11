export type BatchStatus = 'uploaded' | 'parsing' | 'review' | 'committed' | 'failed' | 'needs_ocr'
export type PriceStatus = 'quoted' | 'no_quote' | 'masked'
export type ReviewStatus = 'pending' | 'approved' | 'rejected'
export type ImportTaskStatus = 'queued' | 'running' | 'completed' | 'partial_failed' | 'failed'
export type ImportTaskItemStatus = 'queued' | 'processing' | 'completed' | 'failed'

export interface ImportTaskItem {
  id: number
  position: number
  filename: string
  status: ImportTaskItemStatus
  stage: string
  progress: number
  batch_id: number | null
  candidate_count: number | null
  error_message: string | null
}

export interface ImportTask {
  id: string
  status: ImportTaskStatus
  total_files: number
  completed_files: number
  succeeded_files: number
  failed_files: number
  progress: number
  current_filename: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  items: ImportTaskItem[]
}

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

export interface ReviewAuditLog {
  id: number
  batch_id: number | null
  candidate_id: number | null
  action_type: string
  operator_type: string
  before_data: Record<string, unknown> | null
  after_data: Record<string, unknown> | null
  changed_fields: string[]
  reason: string | null
  agent_run_id: string | null
  model_name: string | null
  rule_version: string | null
  created_at: string
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
  auto_approved: number
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
  conversation_id: string
  memory: Record<string, unknown>
}

export interface AgentConversationMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  sources: AgentSource[] | null
  tools_used: string[] | null
  created_at: string
}

export interface AgentConversation {
  id: string
  title: string
  memory: Record<string, unknown>
  created_at: string
  updated_at: string
  messages: AgentConversationMessage[]
}

export interface MarketMonitorFinding {
  id: number
  finding_type: string
  severity: 'info' | 'warning' | 'danger'
  brand: string | null
  model: string | null
  title: string
  detail: string
  evidence: Record<string, string> | null
  quote_id: number | null
  handling_status: 'open' | 'diagnosed' | 'resolved' | 'dismissed'
  diagnosis: string | null
  recommendation: string | null
  proposed_price: string | null
  proposed_price_status: 'quoted' | 'masked' | 'no_quote' | null
  diagnosis_confidence: number | null
  diagnosis_generated_by_model: boolean
  diagnosis_model: string | null
  diagnosis_run_id: string | null
  handled_reason: string | null
  handled_at: string | null
  created_at: string
}

export interface MarketMonitorRun {
  id: string
  batch_id: number | null
  trigger_type: 'publish' | 'manual' | 'remediation'
  status: 'queued' | 'running' | 'completed' | 'failed'
  quote_date: string | null
  previous_date: string | null
  scanned_quotes: number
  finding_count: number
  danger_count: number
  warning_count: number
  summary: string | null
  generated_by_model: boolean
  model_name: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  findings: MarketMonitorFinding[]
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

export type ReviewDiagnosisField = 'brand' | 'model' | 'storage' | 'color' | 'variant' | 'price_status' | 'price' | 'review_status'

export interface ReviewDiagnosisEvidence {
  category: 'source' | 'history' | 'duplicate' | 'structure' | 'confidence'
  title: string
  detail: string
  severity: 'info' | 'warning' | 'danger'
}

export interface ReviewDiagnosisChange {
  field: ReviewDiagnosisField
  label: string
  current_value: string | number | null
  suggested_value: string | number | null
  reason: string
}

export interface ReviewAgentStep {
  order: number
  phase: 'planning' | 'tool' | 'reasoning' | 'verification'
  title: string
  detail: string
  status: 'completed' | 'fallback'
  tool: string | null
}

export interface ReviewDiagnosis {
  agent_run_id: string
  candidate_id: number
  candidate_signature: string
  severity: 'normal' | 'warning' | 'danger'
  issue_types: string[]
  summary: string
  evidence: ReviewDiagnosisEvidence[]
  recommendations: string[]
  proposed_changes: ReviewDiagnosisChange[]
  requires_confirmation: boolean
  generated_by_model: boolean
  model: string
  source_type: 'excel' | 'image'
  source_label: string
  recognition_confidence: number
  verification_status: 'unverified' | 'human_confirmed'
  agent_mode: 'tool_calling' | 'rule_fallback'
  tools_used: string[]
  workflow_steps: ReviewAgentStep[]
}

export interface ReviewDiagnosisApplyRequest {
  candidate_signature: string
  decision: 'apply_suggestions' | 'mark_no_issue'
  fields: ReviewDiagnosisField[]
  agent_run_id?: string | null
}

export interface ReviewDiagnosisApplyResponse {
  candidate: Candidate
  applied_fields: string[]
  remaining_issue_types: string[]
  verification_summary: string
}

export interface ReviewBatchDiagnosisItem {
  candidate: Candidate
  severity: 'warning' | 'danger'
  issue_types: string[]
  summary: string
  source_label: string
}

export interface ReviewBatchDiagnosis {
  batch_id: number
  batch_signature: string
  scanned_count: number
  safe_count: number
  pending_safe_count: number
  auto_approved_count: number
  warning_count: number
  danger_count: number
  issue_counts: Record<string, number>
  risks: ReviewBatchDiagnosisItem[]
}

export interface ReviewBatchApproveSafeResponse {
  batch_id: number
  approved_count: number
  remaining_pending: number
  agent_run_id: string
}

export interface ReviewSample {
  id: number
  batch_id: number
  candidate_id: number
  status: 'pending' | 'passed' | 'failed'
  note: string | null
  sampled_at: string
  reviewed_at: string | null
  candidate: Candidate
}

export interface ReviewSampleQueueResponse {
  batch_id: number
  requested_count: number
  created_count: number
  eligible_count: number
  items: ReviewSample[]
}

export interface ReviewQualityStats {
  batch_id: number
  auto_approved_total: number
  currently_auto_approved: number
  sampled_total: number
  sampled_pending: number
  sampled_passed: number
  sampled_failed: number
  revoked_total: number
  sample_coverage_percent: number
  verified_accuracy_percent: number | null
}
