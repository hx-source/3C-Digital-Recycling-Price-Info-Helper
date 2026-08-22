import axios from 'axios'
import type { Batch, Candidate, CandidatePage, DashboardSummary, PriceChange, Quote } from './types'

const api = axios.create({ baseURL: '/api/v1', timeout: 120_000 })

export const apiClient = {
  async dashboard() {
    return (await api.get<DashboardSummary>('/dashboard/summary')).data
  },
  async batches() {
    return (await api.get<Batch[]>('/imports')).data
  },
  async upload(form: FormData) {
    return (await api.post<Batch>('/imports', form)).data
  },
  async candidates(batchId: number, page = 1, pageSize = 100) {
    return (await api.get<CandidatePage>(`/imports/${batchId}/candidates`, { params: { page, page_size: pageSize } })).data
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

