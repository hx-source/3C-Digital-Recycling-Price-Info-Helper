<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiClient, errorMessage } from '../api'
import { useMarketStore } from '../stores/market'
import type { Batch, Candidate, CandidateFilterSummary, CandidateSourcePreview, PriceStatus, ReviewStatus } from '../types'

type QuickFilter = 'all' | 'pending' | 'low_confidence' | 'incomplete' | 'merged_source' | 'approved' | 'rejected'
type CandidateSort = 'confidence_asc' | 'confidence_desc' | 'source_asc'
type SourceGroupItem = Candidate & { isNew?: boolean }
type BatchScope = 'active' | 'history'

const market = useMarketStore()
const selectedBatchId = ref<number | null>(null)
const batchQuoteDate = ref('')
const batchScope = ref<BatchScope>('active')
const candidates = ref<Candidate[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const dialogOpen = ref(false)
const editing = reactive<Partial<Candidate>>({})
const sourceGroupDialogOpen = ref(false)
const sourceGroupLoading = ref(false)
const sourceGroupSaving = ref(false)
const sourceGroupReparsing = ref(false)
const sourceGroup = ref<SourceGroupItem[]>([])
const sourceGroupAnchorId = ref<number | null>(null)
const sourceGroupRawText = ref('')
const sourceGroupType = ref<'excel' | 'image' | null>(null)
let sourceGroupRequestVersion = 0
const editorSourceLoading = ref(false)
const editorSourcePreview = ref<CandidateSourcePreview | null>(null)
let editorSourceRequestVersion = 0
const sourceDialogOpen = ref(false)
const sourceLoading = ref(false)
const sourcePreview = ref<CandidateSourcePreview | null>(null)
const quickFilter = ref<QuickFilter>('pending')
const priceStatus = ref<PriceStatus | ''>('')
const sheetName = ref('')
const sort = ref<CandidateSort>('confidence_asc')
const keyword = ref('')
const appliedKeyword = ref('')
const summary = ref<CandidateFilterSummary>({ all: 0, pending: 0, low_confidence: 0, incomplete: 0, approved: 0, rejected: 0, merged_source_groups: 0 })

const selectedBatch = computed(() => market.batches.find(item => item.id === selectedBatchId.value) || null)
const activeBatches = computed(() => market.batches.filter(item => item.status !== 'committed'))
const visibleBatches = computed(() => batchScope.value === 'history' ? market.batches : activeBatches.value)
const batchGroups = computed(() => {
  const groups = new Map<string, Batch[]>()
  for (const batch of visibleBatches.value) {
    const key = uploadDateLabel(batch.created_at)
    groups.set(key, [...(groups.get(key) || []), batch])
  }
  return [...groups.entries()].map(([label, batches]) => ({ label, batches }))
})
const pendingOnPage = computed(() => candidates.value.filter(item => item.review_status === 'pending').length)
const quickFilters = computed(() => [
  { key: 'all' as const, label: '全部', count: summary.value.all },
  { key: 'pending' as const, label: '待复核', count: summary.value.pending },
  { key: 'low_confidence' as const, label: '低置信度', count: summary.value.low_confidence, tone: 'warning' },
  { key: 'incomplete' as const, label: '信息不完整', count: summary.value.incomplete, tone: 'warning' },
  { key: 'merged_source' as const, label: '需拆分', count: summary.value.merged_source_groups, tone: 'warning' },
  { key: 'approved' as const, label: '已通过', count: summary.value.approved },
  { key: 'rejected' as const, label: '已拒绝', count: summary.value.rejected },
])

const boardOptions = ['VIVO', 'OPPO', '红米小米', '华为系列', '华为融合系列', '荣耀报价', '电玩 大疆 鼠标', '图片自动识别']

function uploadDateLabel(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '上传日期未知'
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日上传`
}

function uploadTimeLabel(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间未知'
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function batchOptionLabel(batch: Batch) {
  const kind = batch.source_type === 'image' ? '图片' : '表格'
  const state = batch.status === 'committed' ? '已发布' : batch.status === 'review' ? '待复核' : '处理中'
  return `${uploadTimeLabel(batch.created_at)} · ${kind} · ${batch.total_candidates} 条 · ${state}`
}

function toggleBatchScope() {
  batchScope.value = batchScope.value === 'active' ? 'history' : 'active'
  if (batchScope.value === 'active' && selectedBatch.value?.status === 'committed') {
    selectedBatchId.value = activeBatches.value[0]?.id || null
  }
}

function statusLabel(status: string) {
  return { pending: '待复核', approved: '已通过', rejected: '已拒绝' }[status] || status
}

function sourceActionLabel(row: Candidate) {
  return market.batches.find(item => item.id === row.batch_id)?.source_type === 'excel' ? '查看表格' : '查看原图'
}

function isExcelCandidate(row: Candidate) {
  return market.batches.find(item => item.id === row.batch_id)?.source_type === 'excel'
}

function sourceGroupActionLabel(row: Candidate) {
  return isExcelCandidate(row) ? '编辑单元格' : '整行'
}

function sourceGroupTitle() {
  const unit = sourceGroupType.value === 'excel' ? '编辑单元格' : '整行复核'
  return `${unit} · ${sourceGroup.value.length} 条报价`
}

function sourceGroupOriginLabel() {
  return sourceGroupType.value === 'excel' ? '同一表格单元格' : '同一图片识别区域'
}

function sourceGroupRawLabel() {
  return sourceGroupType.value === 'excel' ? '修正该单元格原文' : '修正这一行原文'
}

function sourceDialogTitle() {
  return sourcePreview.value?.source_type === 'excel' ? '表格来源定位' : '来源原图定位'
}

function excelCellClasses(cell: { is_source: boolean; is_price: boolean }) {
  return { 'excel-source-cell': cell.is_source, 'excel-price-cell': cell.is_price }
}

function priceStatusLabel(status: string) {
  return { quoted: '明确报价', no_quote: '暂无报价', masked: '价格遮挡' }[status] || status
}

function quickReviewStatus(): ReviewStatus | undefined {
  return ['pending', 'approved', 'rejected'].includes(quickFilter.value)
    ? quickFilter.value as ReviewStatus
    : undefined
}

function quickFilterMode(): 'all' | 'low_confidence' | 'incomplete' | 'merged_source' {
  return ['low_confidence', 'incomplete', 'merged_source'].includes(quickFilter.value)
    ? quickFilter.value as 'low_confidence' | 'incomplete' | 'merged_source'
    : 'all'
}

async function loadCandidates() {
  if (!selectedBatchId.value) return
  loading.value = true
  try {
    const data = await apiClient.candidates(selectedBatchId.value, page.value, 100, {
      reviewStatus: quickReviewStatus(),
      priceStatus: priceStatus.value || undefined,
      sheetName: sheetName.value || undefined,
      filterMode: quickFilterMode(),
      search: appliedKeyword.value,
      sort: sort.value,
    })
    candidates.value = data.items
    total.value = data.total
    summary.value = data.summary
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

function applyKeyword() {
  appliedKeyword.value = keyword.value.trim()
}

function resetFilters() {
  quickFilter.value = 'pending'
  priceStatus.value = ''
  sheetName.value = ''
  sort.value = 'confidence_asc'
  keyword.value = ''
  appliedKeyword.value = ''
}

async function loadEditorSource(row: Candidate) {
  const requestVersion = ++editorSourceRequestVersion
  editorSourcePreview.value = null
  editorSourceLoading.value = true
  try {
    const preview = await apiClient.candidateSource(row.id)
    if (requestVersion !== editorSourceRequestVersion) return
    editorSourcePreview.value = preview
  } catch (error) {
    if (requestVersion === editorSourceRequestVersion) ElMessage.error(errorMessage(error))
  } finally {
    if (requestVersion === editorSourceRequestVersion) editorSourceLoading.value = false
  }
}

async function edit(row: Candidate) {
  Object.keys(editing).forEach(key => delete (editing as Record<string, unknown>)[key])
  Object.assign(editing, row)
  dialogOpen.value = true
  await loadEditorSource(row)
}

async function editSourceGroup(row: Candidate) {
  const requestVersion = ++sourceGroupRequestVersion
  sourceGroupDialogOpen.value = true
  sourceGroupLoading.value = true
  sourceGroup.value = []
  sourceGroupAnchorId.value = row.id
  sourceGroupRawText.value = row.raw_text
  sourceGroupType.value = isExcelCandidate(row) ? 'excel' : 'image'
  void loadEditorSource(row)
  try {
    const items = await apiClient.candidateSourceGroup(row.id)
    if (requestVersion !== sourceGroupRequestVersion) return
    sourceGroup.value = items
  } catch (error) {
    if (requestVersion !== sourceGroupRequestVersion) return
    ElMessage.error(errorMessage(error))
    sourceGroupDialogOpen.value = false
  } finally {
    if (requestVersion === sourceGroupRequestVersion) sourceGroupLoading.value = false
  }
}

async function viewSource(row: Candidate) {
  sourceDialogOpen.value = true
  sourceLoading.value = true
  sourcePreview.value = null
  try {
    sourcePreview.value = await apiClient.candidateSource(row.id)
  } catch (error) {
    ElMessage.error(errorMessage(error))
    sourceDialogOpen.value = false
  } finally {
    sourceLoading.value = false
  }
}

function regionStyle() {
  const region = sourcePreview.value?.region
  if (!region) return {}
  return {
    left: `${region.x / region.image_width * 100}%`,
    top: `${region.y / region.image_height * 100}%`,
    width: `${region.width / region.image_width * 100}%`,
    height: `${region.height / region.image_height * 100}%`,
  }
}

function editorCropStyle() {
  const region = editorSourcePreview.value?.region
  if (!region) return {}
  return {
    width: `${region.image_width / region.width * 100}%`,
    transform: `translate(-${region.x / region.image_width * 100}%, -${region.y / region.image_height * 100}%)`,
  }
}

function editorCropFrameStyle() {
  const region = editorSourcePreview.value?.region
  return region ? { aspectRatio: `${region.width} / ${region.height}` } : {}
}

async function saveEdit() {
  if (!editing.id) return
  try {
    await apiClient.updateCandidate(editing.id, {
      quote_date: editing.quote_date,
      category: editing.category,
      brand: editing.brand,
      model: editing.model,
      storage: editing.storage,
      color: editing.color,
      variant: editing.variant,
      price_status: editing.price_status,
      price: editing.price,
      review_status: editing.review_status,
      review_note: editing.review_note,
    })
    dialogOpen.value = false
    ElMessage.success('已保存复核结果')
    await loadCandidates()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

function candidateUpdatePayload(row: Partial<Candidate>) {
  return {
    quote_date: row.quote_date,
    category: row.category,
    brand: row.brand,
    model: row.model,
    storage: row.storage,
    color: row.color,
    variant: row.variant,
    price_status: row.price_status,
    price: row.price,
    review_status: row.review_status,
    review_note: row.review_note,
  }
}

async function saveSourceGroup() {
  if (!sourceGroup.value.length || !sourceGroupAnchorId.value) return
  try {
    sourceGroupSaving.value = true
    sourceGroup.value = await apiClient.replaceCandidateSourceGroup(
      sourceGroupAnchorId.value,
      sourceGroup.value.map(item => ({
        id: item.isNew ? undefined : item.id,
        ...candidateUpdatePayload(item),
      })),
    )
    sourceGroupDialogOpen.value = false
    ElMessage.success(`已保存这一行的 ${sourceGroup.value.length} 条报价`)
    await Promise.all([loadCandidates(), market.refresh()])
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    sourceGroupSaving.value = false
  }
}

function addSourceGroupItem() {
  const template = sourceGroup.value.at(-1)
  if (!template) return
  sourceGroup.value.push({
    ...template,
    id: -(Date.now() + sourceGroup.value.length),
    color: null,
    variant: null,
    price_status: 'no_quote',
    price: null,
    review_status: 'pending',
    review_note: null,
    confidence: 0.99,
    isNew: true,
  })
}

function removeSourceGroupItem(index: number) {
  if (sourceGroup.value.length === 1) {
    ElMessage.warning('这一行至少保留一条报价；如需全部删除，请使用“删除这一行”。')
    return
  }
  sourceGroup.value.splice(index, 1)
}

async function reparseSourceGroup() {
  const candidateId = sourceGroupAnchorId.value
  if (!candidateId || sourceGroupRawText.value.trim().length < 3) return
  try {
    await ElMessageBox.confirm(
      `将按修正后的原文替换当前 ${sourceGroup.value.length} 条记录。旧记录会删除后重新生成，不会产生重复报价。`,
      '重新拆分这一行',
      { confirmButtonText: '确认重新拆分', cancelButtonText: '继续编辑' },
    )
    sourceGroupReparsing.value = true
    sourceGroup.value = await apiClient.reparseSourceLine(candidateId, sourceGroupRawText.value.trim())
    sourceGroupAnchorId.value = sourceGroup.value[0]?.id || candidateId
    sourceGroupRawText.value = sourceGroup.value[0]?.raw_text || sourceGroupRawText.value
    ElMessage.success(`已重新拆分为 ${sourceGroup.value.length} 条报价`)
    await Promise.all([loadCandidates(), market.refresh()])
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  } finally {
    sourceGroupReparsing.value = false
  }
}

async function deleteCandidate(row: Candidate) {
  try {
    await ElMessageBox.confirm(
      `将删除“${row.model || '未命名型号'} ${row.storage || ''} ${row.color || ''}”这一条报价；同一行的其他颜色或型号不会受影响。`,
      '删除单条报价',
      { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning' },
    )
    await apiClient.deleteCandidate(row.id)
    ElMessage.success('已删除这条报价')
    await Promise.all([loadCandidates(), market.refresh()])
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}

async function deleteSourceGroup() {
  const candidateId = sourceGroupAnchorId.value
  if (!candidateId) return
  try {
    await ElMessageBox.confirm(
      `将删除这一来源行解析出的 ${sourceGroup.value.length} 条报价，删除后无法恢复。`,
      '删除整行报价',
      { confirmButtonText: '确认删除整行', cancelButtonText: '取消', type: 'warning' },
    )
    const result = await apiClient.deleteCandidateSourceGroup(candidateId)
    sourceGroupDialogOpen.value = false
    sourceGroup.value = []
    ElMessage.success(`已删除这一行的 ${result.deleted} 条报价`)
    await Promise.all([loadCandidates(), market.refresh()])
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}

async function reviewOne(row: Candidate, status: 'approved' | 'rejected') {
  try {
    await apiClient.updateCandidate(row.id, { review_status: status })
    await loadCandidates()
    await market.refresh()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function reviewAll(status: 'approved' | 'rejected') {
  if (!selectedBatchId.value) return
  await ElMessageBox.confirm(`确认将本批次全部标记为“${statusLabel(status)}”？`, '批量复核')
  try {
    await apiClient.reviewAll(selectedBatchId.value, status)
    await loadCandidates()
    await market.refresh()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function commit() {
  if (!selectedBatchId.value) return
  await ElMessageBox.confirm('发布后会写入正式报价历史，并参与后续涨跌比较。', '发布本批次')
  try {
    const result = await apiClient.commit(selectedBatchId.value)
    ElMessage.success(`已发布 ${result.inserted} 条报价`)
    await market.refresh()
    await loadCandidates()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function deleteSelectedBatch() {
  const batch = selectedBatch.value
  if (!batch) return
  const kind = batch.source_type === 'image' ? '原始图片' : '原始表格'
  try {
    await ElMessageBox.confirm(
      `将删除“${batch.filename}”、${batch.total_candidates} 条待复核记录及${kind}。删除后无法恢复。`,
      '删除导入批次',
      { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning' },
    )
    const result = await apiClient.deleteBatch(batch.id)
    await market.refresh()
    const next = market.batches.find(item => item.status === 'review') || market.batches[0] || null
    selectedBatchId.value = next?.id || null
    if (!next) {
      candidates.value = []
      total.value = 0
      summary.value = { all: 0, pending: 0, low_confidence: 0, incomplete: 0, approved: 0, rejected: 0, merged_source_groups: 0 }
    }
    ElMessage.success(`已删除该批次及 ${result.deleted_candidates} 条待复核记录`)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}

async function purgeAllData() {
  try {
    const { value } = await ElMessageBox.prompt(
      '这会永久删除所有导入图片和表格、全部复核记录及所有已发布报价历史，无法恢复。请输入“清空全部数据”继续。',
      '清空全部数据',
      {
        confirmButtonText: '永久清空',
        cancelButtonText: '取消',
        inputPlaceholder: '清空全部数据',
        inputPattern: /^清空全部数据$/,
        inputErrorMessage: '请输入“清空全部数据”',
        confirmButtonClass: 'purge-confirm-button',
        customClass: 'purge-all-dialog',
      },
    )
    const result = await apiClient.purgeAllData(value)
    selectedBatchId.value = null
    candidates.value = []
    total.value = 0
    summary.value = { all: 0, pending: 0, low_confidence: 0, incomplete: 0, approved: 0, rejected: 0, merged_source_groups: 0 }
    batchScope.value = 'active'
    resetFilters()
    await market.refresh()
    ElMessage.success(`已清空 ${result.deleted_batches} 个导入批次、${result.deleted_candidates} 条复核记录和 ${result.deleted_quotes} 条报价历史`)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}

async function reopenSelectedBatch() {
  const batch = selectedBatch.value
  if (!batch || batch.status !== 'committed') return
  try {
    await ElMessageBox.confirm(
      `将从报价历史撤回该批次已发布的报价，但会保留原图和 ${batch.total_candidates} 条识别记录，便于修正后重新发布。`,
      '撤回到复核',
      { confirmButtonText: '确认撤回', cancelButtonText: '取消', type: 'warning' },
    )
    const result = await apiClient.reopenBatchForReview(batch.id)
    await Promise.all([market.refresh(), loadCandidates()])
    ElMessage.success(`已撤回 ${result.removed_quotes} 条正式报价，${result.reset_candidates} 条记录已回到待复核`)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}

async function saveBatchQuoteDate() {
  const batch = selectedBatch.value
  if (!batch || !batchQuoteDate.value) return ElMessage.warning('请选择正确的报价日期')
  if (batch.quote_date === batchQuoteDate.value) return ElMessage.info('报价日期未发生变化')
  const historyNotice = batch.status === 'committed'
    ? '该批次已发布，修改后会同步调整历史报价日期与涨跌比较。'
    : '修改后会同步调整这一批待复核记录的报价日期。'
  try {
    await ElMessageBox.confirm(historyNotice, '更正报价日期', {
      confirmButtonText: '确认保存日期', cancelButtonText: '取消', type: 'warning',
    })
    const updated = await apiClient.updateBatchQuoteDate(batch.id, batchQuoteDate.value)
    batchQuoteDate.value = updated.quote_date || ''
    await Promise.all([market.refresh(), loadCandidates()])
    ElMessage.success(`已将该批次报价日期更正为 ${batchQuoteDate.value}`)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}

watch([selectedBatchId, quickFilter, priceStatus, sheetName, sort, appliedKeyword], () => {
  page.value = 1
  loadCandidates()
})
watch(page, loadCandidates)
watch(selectedBatch, batch => {
  batchQuoteDate.value = batch?.quote_date || ''
})

onMounted(async () => {
  if (!market.batches.length) await market.refresh()
  const preferred = market.batches.find(item => item.status === 'review') || market.batches[0]
  selectedBatchId.value = preferred?.id || null
})
</script>

<template>
  <section class="view-panel review-view">
    <div class="section-heading">
      <div><p class="eyebrow">REVIEW QUEUE</p><h2>复核工作台</h2></div>
      <div class="review-actions">
        <button class="ghost-action" :disabled="!selectedBatch" @click="reviewAll('rejected')">全部拒绝</button>
        <button class="ghost-action approve" :disabled="!selectedBatch" @click="reviewAll('approved')">全部通过</button>
        <button v-if="selectedBatch?.status === 'committed'" class="ghost-action reopen-batch-action" @click="reopenSelectedBatch">撤回到复核</button>
        <button class="ghost-action delete-batch-action" :disabled="!selectedBatch || selectedBatch.status === 'committed'" @click="deleteSelectedBatch">{{ selectedBatch?.source_type === 'image' ? '删除图片批次' : '删除导入批次' }}</button>
        <button class="ghost-action purge-all-action" @click="purgeAllData">清空全部数据</button>
        <button class="primary-action compact" :disabled="!selectedBatch || selectedBatch.status === 'committed'" @click="commit">发布报价</button>
      </div>
    </div>

    <div class="review-toolbar">
      <label class="batch-picker"><span>{{ batchScope === 'active' ? '待处理批次' : '历史批次' }}</span>
        <div>
          <select v-model="selectedBatchId">
            <option v-if="!batchGroups.length" :value="null" disabled>暂无待处理批次</option>
            <optgroup v-for="group in batchGroups" :key="group.label" :label="group.label">
              <option v-for="batch in group.batches" :key="batch.id" :value="batch.id">{{ batchOptionLabel(batch) }}</option>
            </optgroup>
          </select>
          <button type="button" @click="toggleBatchScope">{{ batchScope === 'active' ? '查看历史' : '只看待处理' }}</button>
        </div>
      </label>
      <label class="batch-date-editor"><span>报价日期</span><div><input v-model="batchQuoteDate" type="date" :disabled="!selectedBatch" /><button type="button" :disabled="!selectedBatch || !batchQuoteDate" @click="saveBatchQuoteDate">保存</button></div></label>
      <div class="review-stat"><span>筛选结果</span><b>{{ total }}</b></div>
      <div class="review-stat warning"><span>低置信度</span><b>{{ summary.low_confidence }}</b></div>
      <div class="review-stat"><span>本页待复核</span><b>{{ pendingOnPage }}</b></div>
    </div>

    <div class="review-filter-nav" aria-label="复核筛选">
      <div class="queue-tabs" role="tablist" aria-label="处理队列">
        <button
          v-for="item in quickFilters"
          :key="item.key"
          :class="['queue-tab', item.tone, { active: quickFilter === item.key }]"
          role="tab"
          :aria-selected="quickFilter === item.key"
          @click="quickFilter = item.key"
        >
          <span>{{ item.label }}</span><b>{{ item.count }}</b>
        </button>
      </div>
      <div class="filter-controls">
        <label class="board-filter"><span>所属板块</span><select v-model="sheetName"><option value="">全部板块</option><option v-for="board in boardOptions" :key="board" :value="board">{{ board }}</option></select></label>
        <label><span>价格状态</span><select v-model="priceStatus"><option value="">全部状态</option><option value="quoted">明确报价</option><option value="no_quote">无报价</option><option value="masked">星号遮挡</option></select></label>
        <label class="review-search"><span>型号或原文</span><input v-model="keyword" placeholder="输入后按回车" @keyup.enter="applyKeyword" /></label>
        <label><span>排序</span><select v-model="sort"><option value="confidence_asc">置信度：低到高</option><option value="confidence_desc">置信度：高到低</option><option value="source_asc">按来源顺序</option></select></label>
        <button class="filter-reset" type="button" @click="resetFilters">重置</button>
      </div>
    </div>

    <div v-if="selectedBatch?.error_message" class="batch-warning">{{ selectedBatch.error_message }}</div>

    <div class="data-table-wrap review-scroll" v-loading="loading">
      <table class="market-table">
        <thead><tr><th>来源</th><th>品牌 / 型号</th><th>规格</th><th>颜色 / 版本</th><th>价格</th><th>置信度</th><th>状态</th><th></th></tr></thead>
        <tbody>
          <tr v-for="row in candidates" :key="row.id" :class="{ uncertain: row.confidence < 0.75 }">
            <td><button class="source-link" type="button" @click.stop="viewSource(row)"><small>{{ row.sheet_name || '图片' }}</small><br><code>{{ row.cell_address || `L${row.id}` }}</code><b>{{ sourceActionLabel(row) }}</b></button></td>
            <td><b>{{ row.brand }}</b><br><span>{{ row.model }}</span></td>
            <td>{{ row.storage || '—' }}</td>
            <td>{{ [row.color, row.variant].filter(Boolean).join(' · ') || '—' }}</td>
            <td><strong v-if="row.price_status === 'quoted'">¥{{ row.price }}</strong><span v-else class="price-state">{{ priceStatusLabel(row.price_status) }}</span></td>
            <td><span class="confidence"><i :style="{ width: `${row.confidence * 100}%` }"></i></span><small>{{ Math.round(row.confidence * 100) }}%</small></td>
            <td><span :class="['review-badge', row.review_status]">{{ statusLabel(row.review_status) }}</span></td>
            <td class="row-actions"><button @click="reviewOne(row, 'approved')">✓</button><button @click="reviewOne(row, 'rejected')">×</button><button @click="viewSource(row)">{{ sourceActionLabel(row) }}</button><button class="source-row-edit" @click="editSourceGroup(row)">{{ sourceGroupActionLabel(row) }}</button><button @click="edit(row)">单条</button><button class="delete-action" @click="deleteCandidate(row)">删除</button></td>
          </tr>
          <tr v-if="!candidates.length"><td colspan="8" class="empty-cell">当前筛选没有记录，调整条件后再试。</td></tr>
        </tbody>
      </table>
    </div>
    <el-pagination v-if="total > 100" v-model:current-page="page" :page-size="100" :total="total" layout="prev, pager, next, total" />

    <el-dialog v-model="dialogOpen" title="修正识别字段" width="680px">
      <div class="edit-grid">
        <div v-if="editorSourceLoading || editorSourcePreview" v-loading="editorSourceLoading" class="editor-source-context wide">
          <template v-if="editorSourcePreview">
            <div v-if="editorSourcePreview.image_url && editorSourcePreview.region" class="editor-source-crop" :style="editorCropFrameStyle()">
              <img :src="editorSourcePreview.image_url" :alt="`${editorSourcePreview.filename} 识别片段`" :style="editorCropStyle()" />
            </div>
            <p>识别片段：{{ editorSourcePreview.raw_text }}</p>
          </template>
        </div>
        <label><span>品牌</span><input v-model="editing.brand" /></label>
        <label><span>型号</span><input v-model="editing.model" /></label>
        <label><span>容量</span><input v-model="editing.storage" /></label>
        <label><span>颜色</span><input v-model="editing.color" /></label>
        <label><span>版本</span><input v-model="editing.variant" /></label>
        <label><span>报价日期</span><input v-model="editing.quote_date" type="date" /></label>
        <label><span>价格状态</span><select v-model="editing.price_status"><option value="quoted">明确报价</option><option value="no_quote">暂无报价</option><option value="masked">价格遮挡</option></select></label>
        <label><span>价格</span><input v-model.number="editing.price" type="number" :disabled="editing.price_status !== 'quoted'" /></label>
        <label class="wide"><span>复核备注</span><textarea v-model="editing.review_note" rows="3"></textarea></label>
      </div>
      <template #footer><button class="ghost-action" @click="dialogOpen = false">取消</button><button class="primary-action compact" @click="saveEdit">保存并返回</button></template>
    </el-dialog>

    <el-dialog v-model="sourceGroupDialogOpen" :title="sourceGroupTitle()" width="min(1080px, 94vw)">
      <div v-loading="sourceGroupLoading" class="source-line-editor">
        <template v-if="sourceGroup.length">
          <div class="source-line-intro">
            <div><span>{{ sourceGroupOriginLabel() }}</span><strong>逐条修改，不会把不同型号或颜色合并成一个报价。</strong></div>
            <div class="source-line-head-actions"><small>{{ sourceGroup[0].sheet_name || '图片' }} · {{ sourceGroup[0].cell_address || `第 ${sourceGroup[0].source_line || '—'} 行` }}</small><button type="button" class="add-source-item" :disabled="sourceGroupReparsing || sourceGroupSaving" @click="addSourceGroupItem">＋ 添加报价</button></div>
          </div>
          <div v-if="editorSourceLoading || editorSourcePreview" v-loading="editorSourceLoading" class="editor-source-context source-group-context">
            <template v-if="editorSourcePreview">
              <div v-if="editorSourcePreview.image_url && editorSourcePreview.region" class="editor-source-crop" :style="editorCropFrameStyle()">
                <img :src="editorSourcePreview.image_url" :alt="`${editorSourcePreview.filename} 识别片段`" :style="editorCropStyle()" />
              </div>
              <p>识别片段：{{ editorSourcePreview.raw_text }}</p>
            </template>
          </div>
          <label class="source-line-text"><span>{{ sourceGroupRawLabel() }}</span><textarea v-model="sourceGroupRawText" rows="2" :disabled="sourceGroupReparsing" /></label>
          <p class="source-line-help">缺少颜色或价格时，直接补到原文中，再点击“按原文重新拆分”。系统会替换旧记录，不会追加重复数据。</p>
          <div class="source-line-list">
            <section v-for="(item, index) in sourceGroup" :key="item.id" class="source-line-item">
              <div class="source-line-number">{{ String(index + 1).padStart(2, '0') }}</div>
              <div class="source-line-fields">
                <label><span>品牌</span><input v-model="item.brand" /></label>
                <label><span>型号</span><input v-model="item.model" /></label>
                <label><span>容量</span><input v-model="item.storage" /></label>
                <label><span>颜色</span><input v-model="item.color" /></label>
                <label><span>版本</span><input v-model="item.variant" /></label>
                <label><span>价格状态</span><select v-model="item.price_status"><option value="quoted">明确报价</option><option value="no_quote">暂无报价</option><option value="masked">价格遮挡</option></select></label>
                <label><span>价格</span><input v-model.number="item.price" type="number" :disabled="item.price_status !== 'quoted'" /></label>
                <label><span>复核结果</span><select v-model="item.review_status"><option value="pending">待复核</option><option value="approved">通过</option><option value="rejected">拒绝</option></select></label>
              </div>
              <button type="button" class="source-line-remove" :disabled="sourceGroupReparsing || sourceGroupSaving" @click="removeSourceGroupItem(index)">删除</button>
            </section>
          </div>
        </template>
      </div>
      <template #footer><button class="ghost-action" @click="sourceGroupDialogOpen = false">取消</button><button class="ghost-action delete-action source-group-delete" :disabled="sourceGroupLoading || sourceGroupReparsing || sourceGroupSaving || !sourceGroup.length" @click="deleteSourceGroup">删除{{ sourceGroupType === 'excel' ? '该单元格' : '这一行' }}</button><button class="ghost-action source-reparse-action" :disabled="sourceGroupLoading || sourceGroupReparsing || sourceGroupSaving || !sourceGroup.length" @click="reparseSourceGroup">按原文重新拆分</button><button class="primary-action compact" :disabled="sourceGroupLoading || sourceGroupReparsing || sourceGroupSaving || !sourceGroup.length" @click="saveSourceGroup">{{ sourceGroupSaving ? '正在保存…' : `保存${sourceGroupType === 'excel' ? '单元格' : '这一行'}报价` }}</button></template>
    </el-dialog>

    <el-dialog v-model="sourceDialogOpen" :title="sourceDialogTitle()" width="min(960px, 94vw)" class="source-preview-dialog">
      <div v-loading="sourceLoading" class="source-preview-body">
        <template v-if="sourcePreview">
          <div class="source-preview-meta">
            <span>{{ sourcePreview.filename }}</span>
            <span>{{ sourcePreview.sheet_name || '未识别板块' }} · {{ sourcePreview.cell_address || '未记录位置' }}</span>
          </div>
          <p class="source-preview-raw">识别原文：{{ sourcePreview.raw_text }}</p>
          <template v-if="sourcePreview.image_url">
            <div class="source-image-scroll">
              <div class="source-image-canvas">
                <img :src="sourcePreview.image_url" :alt="`${sourcePreview.filename} 原图`" />
                <span v-if="sourcePreview.region" class="source-focus" :style="regionStyle()"><b>识别位置</b></span>
              </div>
            </div>
            <p v-if="sourcePreview.region" class="source-preview-tip">{{ sourcePreview.region.precise ? '已按表格行列精确定位。' : '图片缺少完整表格线，已按 OCR 文本区域近似定位。' }}</p>
          </template>
          <template v-if="sourcePreview.excel_context">
            <div class="excel-source-meta">
              <span>工作表 <b>{{ sourcePreview.excel_context.sheet_name }}</b></span>
              <span>型号来源 <b>{{ sourcePreview.excel_context.source_cell }}</b></span>
              <span v-if="sourcePreview.excel_context.price_cell">独立价格 <b>{{ sourcePreview.excel_context.price_cell }}</b></span>
            </div>
            <div class="excel-source-grid-wrap">
              <table class="excel-source-grid">
                <thead><tr><th></th><th v-for="column in sourcePreview.excel_context.columns" :key="column">{{ column }}</th></tr></thead>
                <tbody>
                  <tr v-for="row in sourcePreview.excel_context.rows" :key="row.row">
                    <th>{{ row.row }}</th>
                    <td v-for="cell in row.cells" :key="cell.coordinate" :class="excelCellClasses(cell)">
                      <small>{{ cell.coordinate }}</small><span>{{ cell.value || '—' }}</span><em v-if="cell.merged_range">{{ cell.merged_range }}</em>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p class="excel-source-tip"><i></i> 蓝框：型号/颜色等识别原文　 <b></b> 黄框：独立价格单元格</p>
          </template>
          <p v-if="sourcePreview.message" class="source-preview-message">{{ sourcePreview.message }}</p>
        </template>
      </div>
    </el-dialog>
  </section>
</template>
