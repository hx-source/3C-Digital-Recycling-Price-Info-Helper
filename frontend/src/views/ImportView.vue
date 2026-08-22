<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiClient, errorMessage } from '../api'
import { useMarketStore } from '../stores/market'

const emit = defineEmits<{ navigate: [view: 'review'] }>()
const market = useMarketStore()
const file = ref<File | null>(null)
const sourceName = ref('郑州思物通讯')
const quoteDate = ref('')
const imageSheetName = ref('VIVO')
const manualText = ref('')
const uploading = ref(false)
const dragActive = ref(false)

function chooseFile(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] || null
}

function dropFile(event: DragEvent) {
  dragActive.value = false
  file.value = event.dataTransfer?.files?.[0] || null
}

async function submit() {
  if (!file.value) return ElMessage.warning('请先选择报价文件')
  const form = new FormData()
  form.append('file', file.value)
  form.append('source_name', sourceName.value)
  if (quoteDate.value) form.append('quote_date', quoteDate.value)
  if (manualText.value.trim()) form.append('manual_text', manualText.value)
  if (file.value.type.startsWith('image/')) form.append('image_sheet_name', imageSheetName.value)
  uploading.value = true
  try {
    const batch = await apiClient.upload(form)
    await market.refresh()
    if (batch.status === 'needs_ocr') {
      ElMessage.warning('图片已保存；配置视觉模型或粘贴人工识别文本后可继续')
    } else if (batch.status === 'failed') {
      ElMessage.error(batch.error_message || '解析失败')
    } else {
      ElMessage.success(`识别完成：${batch.total_candidates} 条候选记录`)
      emit('navigate', 'review')
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <section class="view-panel import-view">
    <div class="section-heading">
      <div><p class="eyebrow">SOURCE INTAKE</p><h2>导入一份新的每日报价</h2></div>
      <p class="section-note">Excel 优先直接读取；图片走视觉识别或人工文本兜底。</p>
    </div>

    <div class="import-layout">
      <div
        :class="['drop-zone', { active: dragActive, ready: file }]"
        @dragover.prevent="dragActive = true"
        @dragleave.prevent="dragActive = false"
        @drop.prevent="dropFile"
      >
        <input type="file" accept=".xlsx,.xlsm,.png,.jpg,.jpeg,.webp" @change="chooseFile" />
        <div class="drop-glyph"><span></span><span></span><span></span></div>
        <h3>{{ file ? file.name : '把报价表拖到这里' }}</h3>
        <p>{{ file ? `${(file.size / 1024 / 1024).toFixed(2)} MB · 等待解析` : '支持 XLSX / XLSM / PNG / JPG / WEBP' }}</p>
        <button>{{ file ? '重新选择' : '选择文件' }}</button>
      </div>

      <div class="import-form">
        <label><span>报价来源</span><input v-model="sourceName" placeholder="例如：郑州思物通讯" /></label>
        <label><span>默认报价日期</span><input v-model="quoteDate" type="date" /><small>Excel 会优先读取每个工作表自己的日期</small></label>
        <label v-if="file?.type.startsWith('image/')"><span>图片所属板块</span><select v-model="imageSheetName"><option>VIVO</option><option>OPPO</option><option>红米小米</option><option>华为系列</option><option>荣耀报价</option><option>电玩 大疆 鼠标</option></select></label>
        <label v-if="file?.type.startsWith('image/')" class="wide"><span>人工识别文本（可选）</span><textarea v-model="manualText" rows="5" placeholder="未配置视觉模型时，可粘贴每行报价文本继续全流程"></textarea></label>
        <button class="primary-action" :disabled="!file || uploading" @click="submit">
          {{ uploading ? '正在识别…' : '开始识别并进入复核' }}
        </button>
      </div>
    </div>

    <div class="source-rules">
      <span>解析原则</span>
      <p><b>无价格</b> 保留为 no_quote</p>
      <p><b>星号遮挡</b> 保留为 masked</p>
      <p><b>明确价格</b> 才参与涨跌计算</p>
      <p><b>原始单元格</b> 始终可追溯</p>
    </div>
  </section>
</template>

