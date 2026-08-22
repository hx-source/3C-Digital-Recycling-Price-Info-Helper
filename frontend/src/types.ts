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

