import axios from 'axios'
import type { AgentChatResponse, AgentConversation, AgentMessageInput, Batch, Candidate, CandidatePage, CandidateSourcePreview, DashboardSummary, ExcelPrecheckResult, ImportAgentSummaryRequest, ImportAgentSummaryResponse, ImportTask, MarketMonitorRun, PriceChange, PriceStatus, Quote, ReviewAuditLog, ReviewBatchApproveSafeResponse, ReviewBatchDiagnosis, ReviewDiagnosis, ReviewDiagnosisApplyRequest, ReviewDiagnosisApplyResponse, ReviewQualityStats, ReviewSample, ReviewSampleQueueResponse, ReviewStatus } from './types'

const api = axios.create({ baseURL: '/api/v1', timeout: 120_000 })

export const apiClient = {
  async dashboard() {
    return (await api.get<DashboardSummary>('/dashboard/summary')).data
  },
  async askAgent(question: string, conversationId: string, history: AgentMessageInput[] = []) {
    return (await api.post<AgentChatResponse>('/agent/chat', { question, conversation_id: conversationId, history })).data
  },
  async agentConversations() {
    return (await api.get<AgentConversation[]>('/agent/conversations')).data
  },
  async createAgentConversation() {
    return (await api.post<AgentConversation>('/agent/conversations')).data
  },
  async deleteAgentConversation(conversationId: string) {
    await api.delete(`/agent/conversations/${conversationId}`)
  },
  async summarizeImport(payload: ImportAgentSummaryRequest) {
    return (await api.post<ImportAgentSummaryResponse>('/agent/import-summary', payload)).data
  },
  async diagnoseCandidate(candidateId: number) {
    return (await api.post<ReviewDiagnosis>(`/agent/review-diagnose/${candidateId}`)).data
  },
  async applyCandidateDiagnosis(candidateId: number, payload: ReviewDiagnosisApplyRequest) {
    return (await api.post<ReviewDiagnosisApplyResponse>(`/agent/review-diagnose/${candidateId}/apply`, payload)).data
  },
  async diagnoseBatch(batchId: number) {
    return (await api.post<ReviewBatchDiagnosis>(`/agent/review-diagnose/batches/${batchId}`)).data
  },
  async approveSafeBatchCandidates(batchId: number, batchSignature: string) {
    return (await api.post<ReviewBatchApproveSafeResponse>(`/agent/review-diagnose/batches/${batchId}/approve-safe`, {
      batch_signature: batchSignature,
    })).data
  },
  async revokeAutoApproval(candidateId: number) {
    return (await api.post<Candidate>(`/agent/review-diagnose/${candidateId}/revoke-auto-approval`)).data
  },
  async reviewSamples(batchId: number) {
    return (await api.get<ReviewSample[]>(`/agent/review-quality/batches/${batchId}/samples`)).data
  },
  async generateReviewSamples(batchId: number, count?: number) {
    return (await api.post<ReviewSampleQueueResponse>(`/agent/review-quality/batches/${batchId}/samples`, { count })).data
  },
  async decideReviewSample(sampleId: number, decision: 'passed' | 'failed', note?: string) {
    return (await api.post<ReviewSample>(`/agent/review-quality/samples/${sampleId}/decision`, { decision, note })).data
  },
  async reviewQualityStats(batchId: number) {
    return (await api.get<ReviewQualityStats>(`/agent/review-quality/batches/${batchId}/stats`)).data
  },
  async monitorRuns() {
    return (await api.get<MarketMonitorRun[]>('/monitor/runs')).data
  },
  async latestMonitorRun() {
    return (await api.get<MarketMonitorRun | null>('/monitor/runs/latest')).data
  },
  async monitorRun(runId: string) {
    return (await api.get<MarketMonitorRun>(`/monitor/runs/${runId}`)).data
  },
  async startMonitorRun() {
    return (await api.post<MarketMonitorRun>('/monitor/runs')).data
  },
  async diagnoseMonitorFinding(findingId: number) {
    return (await api.post<MarketMonitorRun['findings'][number]>(`/monitor/findings/${findingId}/diagnose`)).data
  },
  async applyMonitorFinding(findingId: number, proposedPrice: string | null, proposedPriceStatus: string | null, reason?: string) {
    return (await api.post<MarketMonitorRun['findings'][number]>(`/monitor/findings/${findingId}/apply`, { proposed_price: proposedPrice, proposed_price_status: proposedPriceStatus, reason })).data
  },
  async dismissMonitorFinding(findingId: number, reason?: string) {
    return (await api.post<MarketMonitorRun['findings'][number]>(`/monitor/findings/${findingId}/dismiss`, { reason })).data
  },
  async candidateAuditLogs(candidateId: number) {
    return (await api.get<ReviewAuditLog[]>(`/imports/candidates/${candidateId}/audit-logs`)).data
  },
  async batchAuditLogs(batchId: number, actionType = '') {
    return (await api.get<ReviewAuditLog[]>(`/imports/${batchId}/audit-logs`, {
      params: { action_type: actionType || undefined },
    })).data
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
  async createImportTask(form: FormData, onProgress?: (percent: number) => void) {
    return (await api.post<ImportTask>('/imports/tasks', form, {
      onUploadProgress(event) {
        if (!event.total) return
        onProgress?.(Math.max(1, Math.min(100, Math.round(event.loaded / event.total * 100))))
      },
    })).data
  },
  async importTask(taskId: string) {
    return (await api.get<ImportTask>(`/imports/tasks/${taskId}`)).data
  },
  async retryImportTask(taskId: string) {
    return (await api.post<ImportTask>(`/imports/tasks/${taskId}/retry`)).data
  },
  async precheckExcel(form: FormData) {
    return (await api.post<ExcelPrecheckResult>('/imports/precheck-excel', form)).data
  },
  async deleteBatch(batchId: number) {
    return (await api.delete<{ deleted_batches: number; deleted_candidates: number }>(`/imports/${batchId}`)).data
  },
  async purgeAllData(confirmation: string) {
    return (await api.delete<{ deleted_batches: number; deleted_candidates: number; deleted_quotes: number }>('/imports/purge-all', {
      data: { confirmation },
    })).data
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
    filterMode?: 'all' | 'low_confidence' | 'incomplete' | 'merged_source' | 'auto_approved'
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
