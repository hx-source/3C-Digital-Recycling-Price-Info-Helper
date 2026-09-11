<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiClient, errorMessage } from '../api'
import { useMarketStore } from '../stores/market'
import type { ExcelPrecheckIssue, ExcelPrecheckResult, ImportAgentSummaryRequest, ImportAgentSummaryResponse, ImportTask } from '../types'

const emit = defineEmits<{ navigate: [view: 'review'] }>()
const market = useMarketStore()
type QueueStatus = 'waiting' | 'processing' | 'completed' | 'failed'
type ExcelImportMode = 'all' | 'normal_only'
type PrecheckInspection = 'normal' | 'focus' | 'duplicate' | 'abnormal'
type QueueItem = {
  id: string
  file: File
  status: QueueStatus
  progress: number
  stage?: string
  uploadCompleted?: boolean
  candidateCount?: number
  error?: string
}

const queue = ref<QueueItem[]>([])
const sourceName = ref('郑州思物通讯')
const quoteDate = ref('')
const manualText = ref('')
const uploading = ref(false)
const prechecking = ref(false)
const dragActive = ref(false)
const excelPrecheck = ref<ExcelPrecheckResult | null>(null)
const importAgentSummary = ref<ImportAgentSummaryResponse | null>(null)
const summarizing = ref(false)
const inspection = ref<PrecheckInspection>('normal')
const inspectionPanel = ref<HTMLElement | null>(null)
const activeTaskId = ref<string | null>(null)
const activeTaskQueueIndexes = ref<number[]>([])
let summaryRequestId = 0

const imageFiles = computed(() => queue.value.filter(item => item.file.type.startsWith('image/')))
const hasImages = computed(() => imageFiles.value.length > 0)
const singleExcelItem = computed(() => queue.value.length === 1 && /\.(xlsx|xlsm)$/i.test(queue.value[0].file.name) ? queue.value[0] : null)
const canUseManualText = computed(() => queue.value.length === 1 && hasImages.value)
const totalSize = computed(() => queue.value.reduce((sum, item) => sum + item.file.size, 0))
const completedCount = computed(() => queue.value.filter(item => item.status === 'completed').length)
const failedCount = computed(() => queue.value.filter(item => item.status === 'failed').length)
const processedCount = computed(() => completedCount.value + failedCount.value)
const pendingCount = computed(() => queue.value.filter(item => item.status === 'waiting').length)
const currentItem = computed(() => queue.value.find(item => item.status === 'processing') || null)
const progressPercent = computed(() => {
  if (!queue.value.length) return 0
  const totalProgress = queue.value.reduce((sum, item) => {
    if (item.status === 'completed' || item.status === 'failed') return sum + 100
    return sum + item.progress
  }, 0)
  return Math.round(totalProgress / queue.value.length)
})
const hasWorkToProcess = computed(() => queue.value.some(item => item.status === 'waiting' || item.status === 'failed'))
const isComplete = computed(() => queue.value.length > 0 && processedCount.value === queue.value.length)
const sourceType = computed<'excel' | 'image' | 'mixed'>(() => {
  const excelCount = queue.value.filter(item => /\.(xlsx|xlsm)$/i.test(item.file.name)).length
  if (excelCount === queue.value.length) return 'excel'
  if (!excelCount) return 'image'
  return 'mixed'
})
const agentPhase = computed(() => {
  if (isComplete.value) return 3
  if (uploading.value || prechecking.value || summarizing.value || excelPrecheck.value) return 2
  if (queue.value.length) return 1
  return 0
})
const agentHeadline = computed(() => {
  if (uploading.value) return `正在处理第 ${Math.min(processedCount.value + 1, queue.value.length)} 个文件`
  if (prechecking.value) return '正在执行 Excel 入库预检'
  if (summarizing.value) return '正在分析预检结果并整理建议'
  if (importAgentSummary.value) return '本次导入建议已经生成'
  if (queue.value.length) return `已识别为${sourceType.value === 'excel' ? '表格来源' : sourceType.value === 'image' ? '图片来源' : '混合来源'}`
  return '把报价来源交给我'
})
const agentNarrative = computed(() => {
  if (importAgentSummary.value) return importAgentSummary.value.summary
  if (uploading.value) return '我正在调用对应解析流程，并逐个建立可复核批次。'
  if (prechecking.value) return '我会先检查重复、缺价、通配价格与异常涨跌，不会直接写入报价历史。'
  if (summarizing.value) return '本地模型只负责解释检查结果，统计数字仍来自程序规则。'
  if (queue.value.length) return `已接收 ${queue.value.length} 个文件。确认来源和日期后即可开始处理。`
  return '上传 Excel 或图片后，我会判断来源、执行解析与预检，再告诉你应优先检查什么。'
})
const inspectionRecords = computed<ExcelPrecheckIssue[]>(() => {
  const records = excelPrecheck.value?.records || []
  if (inspection.value === 'normal') return records.filter(record => !record.reasons.length)
  if (inspection.value === 'duplicate') return records.filter(record => record.reasons.includes('重复报价'))
  if (inspection.value === 'abnormal') return records.filter(record => record.reasons.some(reason => reason.startsWith('价格波动')))
  return records.filter(record => record.reasons.length)
})
const visibleInspectionRecords = computed(() => inspectionRecords.value.slice(0, 160))

function fileId(file: File) {
  return `${file.name}-${file.size}-${file.lastModified}`
}

function appendFiles(nextFiles: File[]) {
  if (uploading.value || prechecking.value) return
  const knownIds = new Set(queue.value.map(item => item.id))
  const additions = nextFiles
    .filter(file => !knownIds.has(fileId(file)))
    .map(file => ({ id: fileId(file), file, status: 'waiting' as const, progress: 0 }))
  const merged = [...queue.value, ...additions]
  if (merged.length > 30) ElMessage.warning('一次最多导入 30 个文件，已保留前 30 个')
  queue.value = merged.slice(0, 30)
  excelPrecheck.value = null
  resetAgentSummary()
  inspection.value = 'normal'
  if (!canUseManualText.value) manualText.value = ''
}

function chooseFiles(event: Event) {
  const input = event.target as HTMLInputElement
  appendFiles(Array.from(input.files || []))
  input.value = ''
}

function dropFiles(event: DragEvent) {
  dragActive.value = false
  appendFiles(Array.from(event.dataTransfer?.files || []))
}

function removeFile(index: number) {
  if (uploading.value || prechecking.value) return
  queue.value.splice(index, 1)
  excelPrecheck.value = null
  resetAgentSummary()
  inspection.value = 'normal'
  if (!canUseManualText.value) manualText.value = ''
}

function resetAgentSummary() {
  summaryRequestId += 1
  summarizing.value = false
  importAgentSummary.value = null
}

async function requestImportSummary(payload: ImportAgentSummaryRequest, guard?: ExcelPrecheckResult) {
  const requestId = ++summaryRequestId
  summarizing.value = true
  try {
    const result = await apiClient.summarizeImport(payload)
    if (requestId === summaryRequestId && (!guard || excelPrecheck.value === guard)) importAgentSummary.value = result
  } catch {
    // 智能总结是辅助能力，不影响原有导入与复核流程。
  } finally {
    if (requestId === summaryRequestId) summarizing.value = false
  }
}

function applyTaskState(task: ImportTask) {
  task.items.forEach(taskItem => {
    const item = queue.value[activeTaskQueueIndexes.value[taskItem.position] ?? taskItem.position]
    if (!item) return
    item.progress = Math.max(item.progress, taskItem.progress)
    item.stage = taskItem.stage
    item.status = taskItem.status === 'queued' ? 'waiting' : taskItem.status
    item.candidateCount = taskItem.candidate_count ?? undefined
    item.error = taskItem.error_message ?? undefined
  })
}

async function pollTask(taskId: string) {
  while (activeTaskId.value === taskId) {
    const task = await apiClient.importTask(taskId)
    applyTaskState(task)
    if (['completed', 'partial_failed', 'failed'].includes(task.status)) return task
    await new Promise(resolve => window.setTimeout(resolve, 700))
  }
  throw new Error('导入任务已取消')
}

async function requestExcelPrecheck() {
  const item = singleExcelItem.value
  if (!item) return
  prechecking.value = true
  try {
    const form = new FormData()
    form.append('file', item.file)
    if (quoteDate.value) form.append('quote_date', quoteDate.value)
    const report = await apiClient.precheckExcel(form)
    excelPrecheck.value = report
    inspection.value = 'normal'
    ElMessage.success(`预检完成：${excelPrecheck.value.total_candidates} 条候选记录`)
    void requestImportSummary({
      filename: item.file.name,
      source_type: 'excel',
      total_candidates: report.total_candidates,
      normal_candidates: report.normal_candidates,
      needs_review_candidates: report.needs_review_candidates,
      duplicate_candidates: report.duplicate_candidates,
      abnormal_price_candidates: report.abnormal_price_candidates,
      incomplete_candidates: report.incomplete_candidates,
      no_quote_candidates: report.no_quote_candidates,
      masked_candidates: report.masked_candidates,
    }, report)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    prechecking.value = false
  }
}

async function runQueue(excelImportMode: ExcelImportMode = 'all') {
  const itemsToProcess = queue.value.filter(item => item.status === 'waiting' || item.status === 'failed')
  if (!itemsToProcess.length) return
  const retryExisting = Boolean(activeTaskId.value) && itemsToProcess.every(item => item.status === 'failed')
  const currentSource = sourceName.value
  const currentDate = quoteDate.value
  const currentManualText = canUseManualText.value ? manualText.value.trim() : ''
  uploading.value = true
  itemsToProcess.forEach(item => {
    item.status = 'processing'
    item.progress = 0
    item.stage = 'uploading'
    item.error = undefined
    item.candidateCount = undefined
  })
  try {
    let task: ImportTask
    if (activeTaskId.value && retryExisting) {
      task = await apiClient.retryImportTask(activeTaskId.value)
    } else {
      const form = new FormData()
      activeTaskQueueIndexes.value = itemsToProcess.map(item => queue.value.indexOf(item))
      itemsToProcess.forEach(item => form.append('files', item.file))
      form.append('source_name', currentSource)
      if (currentDate) form.append('quote_date', currentDate)
      if (currentManualText) form.append('manual_text', currentManualText)
      form.append('excel_import_mode', excelImportMode)
      task = await apiClient.createImportTask(form, percent => {
        itemsToProcess.forEach(item => { item.progress = Math.max(item.progress, Math.round(percent * 0.1)) })
      })
      activeTaskId.value = task.id
    }
    applyTaskState(task)
    await pollTask(task.id)
  } catch (error) {
    itemsToProcess.filter(item => item.status === 'processing').forEach(item => {
      item.status = 'failed'
      item.error = errorMessage(error)
    })
  } finally {
    uploading.value = false
  }
  await market.refresh()
  const recognized = queue.value.filter(item => item.status === 'completed')
  const candidates = recognized.reduce((sum, item) => sum + (item.candidateCount || 0), 0)
  if (failedCount.value) ElMessage.warning(`已完成 ${recognized.length} 个文件、${candidates} 条候选；${failedCount.value} 个文件可重试`)
  else ElMessage.success(`已完成 ${recognized.length} 个文件，共 ${candidates} 条候选记录`)
  if (recognized.length) void requestImportSummary({
    filename: queue.value.length === 1 ? queue.value[0].file.name : `${queue.value.length} 个报价文件`,
    source_type: sourceType.value,
    total_candidates: candidates,
  })
}

async function submit() {
  if (!queue.value.length) return ElMessage.warning('请先选择报价图片或表格')
  if (singleExcelItem.value && !excelPrecheck.value) {
    await requestExcelPrecheck()
    return
  }
  await runQueue()
}

async function confirmExcelImport(mode: ExcelImportMode) {
  excelPrecheck.value = null
  resetAgentSummary()
  await runQueue(mode)
}

function statusLabel(item: QueueItem) {
  if (item.status === 'processing') return item.stage === 'uploading' ? `正在上传 ${item.progress}%` : item.stage === 'persisting' ? `正在入库 ${item.progress}%` : `正在解析 ${item.progress}%`
  if (item.status === 'completed') return `已完成 · ${item.candidateCount || 0} 条`
  if (item.status === 'failed') return '识别失败'
  return '等待识别'
}

async function openInspection(view: PrecheckInspection) {
  inspection.value = view
  await nextTick()
  inspectionPanel.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

function formatMoney(value: number | null) {
  return value === null ? '—' : `¥${value}`
}

function priceStatusLabel(status: string) {
  return { quoted: '明确报价', no_quote: '暂无报价', masked: '价格待确认' }[status] || status
}
</script>

<template>
  <section class="view-panel import-view">
    <div class="section-heading">
      <div><h2>把今天的报价来源交给我</h2></div>
      <p class="section-note">识别来源、调用解析、解释风险，再由你决定如何进入复核。</p>
    </div>

    <section class="import-agent-guide" aria-live="polite">
      <span class="import-agent-avatar">导</span>
      <div class="import-agent-message">
        <small>当前任务</small>
        <strong>{{ agentHeadline }}</strong>
        <p>{{ agentNarrative }}</p>
        <ul v-if="importAgentSummary?.recommendations.length">
          <li v-for="item in importAgentSummary.recommendations" :key="item">{{ item }}</li>
        </ul>
        <em v-if="importAgentSummary">{{ importAgentSummary.generated_by_model ? `本地模型 ${importAgentSummary.model} 已参与总结` : '已使用本地规则生成可靠建议' }}</em>
      </div>
      <ol class="import-agent-steps">
        <li :class="{ active: agentPhase === 1, done: agentPhase > 1 }"><i>1</i><span>接收来源</span></li>
        <li :class="{ active: agentPhase === 2, done: agentPhase > 2 }"><i>2</i><span>解析检查</span></li>
        <li :class="{ active: agentPhase === 3 }"><i>3</i><span>进入复核</span></li>
      </ol>
    </section>

    <div class="import-layout">
      <div
        :class="['drop-zone', { active: dragActive, ready: queue.length, processing: uploading || prechecking }]"
        @dragover.prevent="!uploading && !prechecking && (dragActive = true)"
        @dragleave.prevent="!uploading && !prechecking && (dragActive = false)"
        @drop.prevent="dropFiles"
      >
        <input type="file" accept=".xlsx,.xlsm,.png,.jpg,.jpeg,.webp" multiple :disabled="uploading || prechecking" @change="chooseFiles" />
        <div class="drop-glyph"><span></span><span></span><span></span></div>
        <h3>{{ queue.length ? `已选 ${queue.length} 个文件` : '把今天的报价表或图片拖到这里' }}</h3>
        <p>{{ queue.length ? `${(totalSize / 1024 / 1024).toFixed(2)} MB · 可继续拖入或选择文件追加 · 单个 Excel 会先执行预检` : '支持 XLSX / XLSM，也兼容一次选择多张 PNG / JPG / WEBP' }}</p>
        <button>{{ prechecking ? '正在检查表格' : uploading ? '正在处理队列' : queue.length ? '继续添加文件' : '选择文件' }}</button>
      </div>

      <div class="import-form">
        <label><span>报价来源</span><input v-model="sourceName" placeholder="例如：郑州思物通讯" /></label>
        <label><span>默认报价日期</span><input v-model="quoteDate" type="date" /><small>图片会使用该日期；Excel 优先读取工作表日期</small></label>
        <div v-if="queue.length" class="file-manifest wide">
          <div class="manifest-head"><span>本次入库清单</span><small>{{ imageFiles.length ? `${imageFiles.length} 张图片将读取图内所属板块` : '单个 Excel 将先进行入库预检' }}</small></div>
          <ul>
            <li v-for="(item, index) in queue" :key="item.id" :class="`queue-${item.status}`">
              <i>{{ item.file.type.startsWith('image/') ? '图片' : '表格' }}</i>
              <span>{{ item.file.name }}</span>
              <small>{{ (item.file.size / 1024 / 1024).toFixed(2) }} MB</small>
              <em :title="item.error">{{ statusLabel(item) }}</em>
              <button v-if="!uploading" type="button" @click="removeFile(index)">移除</button>
              <p v-if="item.error" class="queue-error">失败原因：{{ item.error }}</p>
            </li>
          </ul>
        </div>
        <label v-if="canUseManualText && !uploading" class="wide"><span>人工识别文本（可选）</span><textarea v-model="manualText" rows="4" placeholder="自动识别异常时，可为这一张图片粘贴报价原文"></textarea></label>
        <p v-else-if="queue.length > 1" class="auto-note wide"><b>所属板块识别已开启</b> · 系统优先读取图片标题下方的“××系列”栏目；未读到时才按型号词推断。</p>
        <section v-if="excelPrecheck" class="excel-precheck wide" aria-live="polite">
          <header><div><strong>入库前已完成检查</strong></div><p>{{ excelPrecheck.total_candidates }} 条候选记录 · 可选择全部复核，或仅保留无风险记录</p></header>
          <div class="precheck-metrics">
            <button :class="{ clear: true, active: inspection === 'normal' }" type="button" @click="openInspection('normal')"><small>可直接进入复核</small><b>{{ excelPrecheck.normal_candidates }}</b><em>查看清单 ↓</em></button>
            <button :class="{ active: inspection === 'focus' }" type="button" @click="openInspection('focus')"><small>需重点检查</small><b>{{ excelPrecheck.needs_review_candidates }}</b><em>查看疑点 ↓</em></button>
            <button :class="{ flagged: excelPrecheck.duplicate_candidates, active: inspection === 'duplicate' }" type="button" :disabled="!excelPrecheck.duplicate_candidates" @click="openInspection('duplicate')"><small>重复报价</small><b>{{ excelPrecheck.duplicate_candidates }}</b><em>查看重复 ↓</em></button>
            <button :class="{ flagged: excelPrecheck.abnormal_price_candidates, active: inspection === 'abnormal' }" type="button" :disabled="!excelPrecheck.abnormal_price_candidates" @click="openInspection('abnormal')"><small>异常波动</small><b>{{ excelPrecheck.abnormal_price_candidates }}</b><em>查看价差 ↓</em></button>
          </div>
          <section ref="inspectionPanel" class="precheck-inspection">
            <div class="precheck-inspection-table-wrap">
              <table class="precheck-inspection-table">
                <thead><tr><th>来源位置</th><th>识别结果</th><th>本次价格</th><th>检查结果</th><th>原文</th></tr></thead>
                <tbody>
                  <tr v-for="record in visibleInspectionRecords" :key="`${record.sheet_name}-${record.cell_address}-${record.model}-${record.color}-${record.price}`">
                    <td><b>{{ record.sheet_name || '未识别板块' }}</b><small>{{ record.cell_address || '未定位单元格' }}</small></td>
                    <td><b>{{ [record.brand, record.model].filter(Boolean).join(' ') || '待补充型号' }}</b><small>{{ [record.storage, record.color].filter(Boolean).join(' · ') || '—' }}</small></td>
                    <td><b>{{ record.price_status === 'quoted' ? formatMoney(record.price) : priceStatusLabel(record.price_status) }}</b><small v-if="record.previous_price !== null">上期 {{ formatMoney(record.previous_price) }} · {{ record.difference !== null && record.difference > 0 ? '+' : '' }}{{ record.difference }}</small></td>
                    <td><template v-if="record.reasons.length"><em v-for="reason in record.reasons" :key="reason">{{ reason }}</em><small v-if="record.duplicate_detail">{{ record.duplicate_detail }}</small></template><span v-else class="precheck-clear-state">可直接进入复核</span></td>
                    <td class="precheck-raw-text">{{ record.raw_text }}</td>
                  </tr>
                  <tr v-if="!visibleInspectionRecords.length"><td colspan="5" class="empty-cell">这一类没有记录。</td></tr>
                </tbody>
              </table>
            </div>
            <p v-if="inspectionRecords.length > visibleInspectionRecords.length" class="precheck-inspection-limit">为保证导入页流畅，此处显示前 {{ visibleInspectionRecords.length }} 条。完整数据导入后可在复核工作台筛选。</p>
          </section>
          <footer><p>“仅导入正常记录”不会写入以上风险项；如需保留它们，请选择“全部进入复核”。</p><div><button type="button" class="ghost-action" :disabled="uploading" @click="confirmExcelImport('normal_only')">仅导入正常 {{ excelPrecheck.normal_candidates }} 条</button><button type="button" class="primary-action compact" :disabled="uploading" @click="confirmExcelImport('all')">全部 {{ excelPrecheck.total_candidates }} 条进入复核</button></div></footer>
        </section>
        <div v-if="uploading || processedCount" class="recognition-progress wide" aria-live="polite">
          <div><strong>{{ uploading ? `${currentItem?.stage === 'uploading' ? '正在上传' : currentItem?.stage === 'persisting' ? '正在入库' : '正在解析'} ${processedCount + 1} / ${queue.length} 个文件` : `识别完成 ${completedCount} / ${queue.length} 个文件` }}</strong><span>{{ progressPercent }}%</span></div>
          <div class="progress-track"><i :style="{ width: `${progressPercent}%` }"></i></div>
          <p v-if="currentItem">当前：{{ currentItem.file.name }} · {{ currentItem.progress }}%</p>
          <p v-else-if="failedCount">{{ failedCount }} 个文件识别失败，可点击下方按钮重试。</p>
          <p v-else>已完成 {{ completedCount }} 个文件，共可进入复核。</p>
        </div>
        <button v-if="!excelPrecheck" class="primary-action" :disabled="!hasWorkToProcess || uploading || prechecking" @click="submit">
          {{ prechecking ? '正在检查 Excel…' : uploading ? `正在识别 ${processedCount + 1} / ${queue.length}…` : failedCount ? `重试 ${failedCount} 个失败文件` : isComplete ? '全部文件已识别完成' : singleExcelItem ? '检查 Excel 后选择导入方式' : `开始识别 ${pendingCount} 个文件` }}
        </button>
        <button v-if="completedCount" type="button" class="ghost-action review-result-action" @click="emit('navigate', 'review')">查看 {{ completedCount }} 个复核批次</button>
      </div>
    </div>

  </section>
</template>
