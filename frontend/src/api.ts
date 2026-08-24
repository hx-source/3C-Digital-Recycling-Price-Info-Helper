import axios from 'axios'
import type { Batch, Candidate, CandidatePage, CandidateSourcePreview, DashboardSummary, PriceChange, PriceStatus, Quote, ReviewStatus } from './types'

const api = axios.create({ baseURL: '/api/v1', timeout: 120_000 })

export const apiClient = {
  async dashboard() {
    return (await api.get<DashboardSummary>('/dashboard/summary')).data
  },
  async batches() {
    return (await api.get<Batch[]>('/imports')).data
  },
  async upload(form: FormData, onProgress?: (percent: number, completed: boolean) => void) {
    return (await api.post<Batch>('/imports', form, {
      onUploadProgress(event) {
        if (!event.total) return
        const completed = event.loaded >= event.total
        const percent = Math.max(1, Math.min(20, Math.round(event.loaded / event.total * 20)))
        onProgress?.(percent, completed)
      },
    })).data
  },
  async uploadBulk(form: FormData) {
    return (await api.post<Batch[]>('/imports/bulk', form)).data
  },
  async deleteBatch(batchId: number) {
    return (await api.delete<{ deleted_batches: number; deleted_candidates: number }>(`/imports/${batchId}`)).data
  },
  async updateBatchQuoteDate(batchId: number, quoteDate: string) {
    return (await api.patch<Batch>(`/imports/${batchId}/quote-date`, { quote_date: quoteDate })).data
  },
  async reopenBatchForReview(batchId: number) {
    return (await api.post<{ batch_id: number; removed_quotes: number; reset_candidates: number }>(`/imports/${batchId}/reopen-review`)).data
  },
  async candidates(batchId: number, page = 1, pageSize = 100, filters: {
    reviewStatus?: ReviewStatus
    priceStatus?: PriceStatus
    sheetName?: string
    filterMode?: 'all' | 'low_confidence' | 'incomplete' | 'merged_source'
    search?: string
    sort?: 'confidence_asc' | 'confidence_desc' | 'source_asc'
  } = {}) {
    return (await api.get<CandidatePage>(`/imports/${batchId}/candidates`, {
      params: {
        page,
        page_size: pageSize,
        review_status: filters.reviewStatus,
        price_status: filters.priceStatus,
        sheet_name: filters.sheetName,
        filter_mode: filters.filterMode || 'all',
        search: filters.search || undefined,
        sort: filters.sort || 'confidence_asc',
      },
    })).data
  },
  async candidateSource(candidateId: number) {
    return (await api.get<CandidateSourcePreview>(`/imports/candidates/${candidateId}/source`)).data
  },
  async candidateSourceGroup(candidateId: number) {
    return (await api.get<Candidate[]>(`/imports/candidates/${candidateId}/source-group`)).data
  },
  async replaceCandidateSourceGroup(candidateId: number, items: Array<Partial<Candidate> & { id?: number }>) {
    return (await api.put<Candidate[]>(`/imports/candidates/${candidateId}/source-group`, { items })).data
  },
  async reparseSourceLine(candidateId: number, rawText: string) {
    return (await api.post<Candidate[]>(`/imports/candidates/${candidateId}/reparse-source-line`, { raw_text: rawText })).data
  },
  async deleteCandidate(candidateId: number) {
    return (await api.delete<{ deleted: number }>(`/imports/candidates/${candidateId}`)).data
  },
  async deleteCandidateSourceGroup(candidateId: number) {
    return (await api.delete<{ deleted: number }>(`/imports/candidates/${candidateId}/source-group`)).data
  },
  async updateCandidate(id: number, payload: Partial<Candidate>) {
    return (await api.patch<Candidate>(`/imports/candidates/${id}`, payload)).data
  },
  async reviewAll(batchId: number, reviewStatus: 'approved' | 'rejected') {
    return (await api.post(`/imports/${batchId}/review-all`, null, { params: { review_status: reviewStatus } })).data
  },
  async commit(batchId: number) {
    return (await api.post(`/imports/${batchId}/commit`)).data
  },
  async reparseImage(batchId: number, form: FormData) {
    return (await api.post<Batch>(`/imports/${batchId}/reparse-image`, form)).data
  },
  async quotes(page = 1, pageSize = 100, search = '') {
    return (await api.get<{ items: Quote[]; total: number }>('/quotes', { params: { page, page_size: pageSize, search: search || undefined } })).data
  },
  async changes(search = '') {
    return (await api.get<PriceChange[]>('/quotes/changes', { params: { search: search || undefined } })).data
  },
}

export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    return String(error.response?.data?.detail || error.message)
  }
  return error instanceof Error ? error.message : String(error)
}
