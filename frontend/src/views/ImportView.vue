<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiClient, errorMessage } from '../api'
import { useMarketStore } from '../stores/market'

const emit = defineEmits<{ navigate: [view: 'review'] }>()
const market = useMarketStore()
type QueueStatus = 'waiting' | 'processing' | 'completed' | 'failed'
type QueueItem = {
  id: string
  file: File
  status: QueueStatus
  progress: number
  uploadCompleted?: boolean
  candidateCount?: number
  error?: string
}

const queue = ref<QueueItem[]>([])
const sourceName = ref('郑州思物通讯')
const quoteDate = ref('')
const manualText = ref('')
const uploading = ref(false)
const dragActive = ref(false)

const imageFiles = computed(() => queue.value.filter(item => item.file.type.startsWith('image/')))
const hasImages = computed(() => imageFiles.value.length > 0)
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

function fileId(file: File) {
  return `${file.name}-${file.size}-${file.lastModified}`
}

function appendFiles(nextFiles: File[]) {
  if (uploading.value) return
  const knownIds = new Set(queue.value.map(item => item.id))
  const additions = nextFiles
    .filter(file => !knownIds.has(fileId(file)))
    .map(file => ({ id: fileId(file), file, status: 'waiting' as const, progress: 0 }))
  const merged = [...queue.value, ...additions]
  if (merged.length > 30) ElMessage.warning('一次最多导入 30 个文件，已保留前 30 个')
  queue.value = merged.slice(0, 30)
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
  if (uploading.value) return
  queue.value.splice(index, 1)
  if (!canUseManualText.value) manualText.value = ''
}

function animateToComplete(item: QueueItem) {
  return new Promise<void>(resolve => {
    const timer = window.setInterval(() => {
      item.progress = Math.min(100, item.progress + Math.max(2, Math.ceil((100 - item.progress) * 0.14)))
      if (item.progress === 100) {
        window.clearInterval(timer)
        resolve()
      }
    }, 28)
  })
}

async function submit() {
  if (!queue.value.length) return ElMessage.warning('请先选择报价图片或表格')
  const itemsToProcess = queue.value.filter(item => item.status === 'waiting' || item.status === 'failed')
  if (!itemsToProcess.length) return
  const currentSource = sourceName.value
  const currentDate = quoteDate.value
  const currentManualText = canUseManualText.value ? manualText.value.trim() : ''
  uploading.value = true
  for (const item of itemsToProcess) {
    item.status = 'processing'
    item.progress = 1
    item.uploadCompleted = false
    item.error = undefined
    item.candidateCount = undefined
    const form = new FormData()
    form.append('file', item.file)
    form.append('source_name', currentSource)
    if (currentDate) form.append('quote_date', currentDate)
    if (currentManualText) form.append('manual_text', currentManualText)
    const recognitionProgress = window.setInterval(() => {
      if (!item.uploadCompleted || item.status !== 'processing' || item.progress >= 95) return
      item.progress = Math.min(95, item.progress + Math.max(1, Math.ceil((95 - item.progress) * 0.055)))
    }, 480)
    try {
      const batch = await apiClient.upload(form, (percent, completed) => {
        item.progress = Math.max(item.progress, percent)
        item.uploadCompleted = completed
      })
      if (batch.status === 'review' || batch.status === 'committed') {
        await animateToComplete(item)
        item.status = 'completed'
        item.candidateCount = batch.total_candidates
      } else {
        await animateToComplete(item)
        item.status = 'failed'
        item.error = batch.error_message || '识别未生成可复核结果'
      }
    } catch (error) {
      await animateToComplete(item)
      item.status = 'failed'
      item.error = errorMessage(error)
    } finally {
      window.clearInterval(recognitionProgress)
    }
  }
  uploading.value = false
  await market.refresh()
  const recognized = queue.value.filter(item => item.status === 'completed')
  const candidates = recognized.reduce((sum, item) => sum + (item.candidateCount || 0), 0)
  if (failedCount.value) ElMessage.warning(`已完成 ${recognized.length} 个文件、${candidates} 条候选；${failedCount.value} 个文件可重试`)
  else ElMessage.success(`已完成 ${recognized.length} 个文件，共 ${candidates} 条候选记录`)
}

function statusLabel(item: QueueItem) {
  if (item.status === 'processing') return item.progress < 20 ? `正在上传 ${item.progress}%` : `正在识别 ${item.progress}%`
  if (item.status === 'completed') return `已完成 · ${item.candidateCount || 0} 条`
  if (item.status === 'failed') return '识别失败'
  return '等待识别'
}
</script>

<template>
  <section class="view-panel import-view">
    <div class="section-heading">
      <div><p class="eyebrow">IMAGE INTAKE</p><h2>把今天的报价图，一次送进复核台</h2></div>
      <p class="section-note">图片优先读取标题下方的所属板块并分别建档；Excel 仍可直接读取单元格。</p>
    </div>

    <div class="import-layout">
      <div
        :class="['drop-zone', { active: dragActive, ready: queue.length, processing: uploading }]"
        @dragover.prevent="!uploading && (dragActive = true)"
        @dragleave.prevent="!uploading && (dragActive = false)"
        @drop.prevent="dropFiles"
      >
        <input type="file" accept=".xlsx,.xlsm,.png,.jpg,.jpeg,.webp" multiple :disabled="uploading" @change="chooseFiles" />
        <div class="drop-glyph"><span></span><span></span><span></span></div>
        <h3>{{ queue.length ? `已选 ${queue.length} 个文件` : '把今天的报价图拖到这里' }}</h3>
        <p>{{ queue.length ? `${(totalSize / 1024 / 1024).toFixed(2)} MB · 可继续拖入或选择文件追加 · 每张图片独立识别` : '支持一次选择多张 PNG / JPG / WEBP，也兼容 XLSX / XLSM' }}</p>
        <button>{{ uploading ? '正在处理队列' : queue.length ? '继续添加文件' : '选择文件' }}</button>
      </div>

      <div class="import-form">
        <label><span>报价来源</span><input v-model="sourceName" placeholder="例如：郑州思物通讯" /></label>
        <label><span>默认报价日期</span><input v-model="quoteDate" type="date" /><small>图片会使用该日期；Excel 优先读取工作表日期</small></label>
        <div v-if="queue.length" class="file-manifest wide">
          <div class="manifest-head"><span>本次入库清单</span><small>{{ imageFiles.length }} 张图片将读取图内所属板块</small></div>
          <ul>
            <li v-for="(item, index) in queue" :key="item.id" :class="`queue-${item.status}`">
              <i>{{ item.file.type.startsWith('image/') ? 'IMG' : 'XLS' }}</i>
              <span>{{ item.file.name }}</span>
              <small>{{ (item.file.size / 1024 / 1024).toFixed(2) }} MB</small>
              <em :title="item.error">{{ statusLabel(item) }}</em>
              <button v-if="!uploading" type="button" @click="removeFile(index)">移除</button>
            </li>
          </ul>
        </div>
        <label v-if="canUseManualText && !uploading" class="wide"><span>人工识别文本（可选）</span><textarea v-model="manualText" rows="4" placeholder="自动识别异常时，可为这一张图片粘贴报价原文"></textarea></label>
        <p v-else-if="queue.length > 1" class="auto-note wide"><b>所属板块识别已开启</b> · 系统优先读取图片标题下方的“××系列”栏目；未读到时才按型号词推断。</p>
        <div v-if="uploading || processedCount" class="recognition-progress wide" aria-live="polite">
          <div><strong>{{ uploading ? `${currentItem && currentItem.progress < 20 ? '正在上传' : '正在识别'} ${processedCount + 1} / ${queue.length} 个文件` : `识别完成 ${completedCount} / ${queue.length} 个文件` }}</strong><span>{{ progressPercent }}%</span></div>
          <div class="progress-track"><i :style="{ width: `${progressPercent}%` }"></i></div>
          <p v-if="currentItem">当前：{{ currentItem.file.name }} · {{ currentItem.progress }}%</p>
          <p v-else-if="failedCount">{{ failedCount }} 个文件识别失败，可点击下方按钮重试。</p>
          <p v-else>已完成 {{ completedCount }} 个文件，共可进入复核。</p>
        </div>
        <button class="primary-action" :disabled="!hasWorkToProcess || uploading" @click="submit">
          {{ uploading ? `正在识别 ${processedCount + 1} / ${queue.length}…` : failedCount ? `重试 ${failedCount} 个失败文件` : isComplete ? '全部文件已识别完成' : `开始识别 ${pendingCount} 个文件` }}
        </button>
        <button v-if="completedCount" type="button" class="ghost-action review-result-action" @click="emit('navigate', 'review')">查看 {{ completedCount }} 个复核批次</button>
      </div>
    </div>

    <div class="source-rules">
      <span>批量识别原则</span>
      <p><b>一图一批次</b> 方便逐张回溯</p>
      <p><b>所属板块</b> 优先读取图内栏目标题</p>
      <p><b>无价格 / 星号</b> 原样保留</p>
      <p><b>最终发布</b> 必经人工复核</p>
    </div>
  </section>
</template>
