<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiClient, errorMessage } from '../api'
import { useMarketStore } from '../stores/market'
import type { Batch, Candidate } from '../types'

const market = useMarketStore()
const selectedBatchId = ref<number | null>(null)
const candidates = ref<Candidate[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const dialogOpen = ref(false)
const editing = reactive<Partial<Candidate>>({})

const selectedBatch = computed(() => market.batches.find(item => item.id === selectedBatchId.value) || null)
const pending = computed(() => candidates.value.filter(item => item.review_status === 'pending').length)
const lowConfidence = computed(() => candidates.value.filter(item => item.confidence < 0.75).length)

function statusLabel(status: string) {
  return { pending: '待复核', approved: '已通过', rejected: '已拒绝' }[status] || status
}

async function loadCandidates() {
  if (!selectedBatchId.value) return
  loading.value = true
  try {
    const data = await apiClient.candidates(selectedBatchId.value, page.value, 100)
    candidates.value = data.items
    total.value = data.total
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

function edit(row: Candidate) {
  Object.keys(editing).forEach(key => delete (editing as Record<string, unknown>)[key])
  Object.assign(editing, row)
  dialogOpen.value = true
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

async function reviewOne(row: Candidate, status: 'approved' | 'rejected') {
  await apiClient.updateCandidate(row.id, { review_status: status })
  row.review_status = status
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

watch(selectedBatchId, () => { page.value = 1; loadCandidates() })
watch(page, loadCandidates)

onMounted(async () => {
  if (!market.batches.length) await market.refresh()
  const preferred = market.batches.find(item => item.status === 'review') || market.batches[0]
  selectedBatchId.value = preferred?.id || null
})
</script>

<template>
  <section class="view-panel review-view">
    <div class="section-heading">
      <div><p class="eyebrow">HUMAN IN THE LOOP</p><h2>复核后再让价格进入历史</h2></div>
      <div class="review-actions">
        <button class="ghost-action" :disabled="!selectedBatch" @click="reviewAll('rejected')">全部拒绝</button>
        <button class="ghost-action approve" :disabled="!selectedBatch" @click="reviewAll('approved')">全部通过</button>
        <button class="primary-action compact" :disabled="!selectedBatch || selectedBatch.status === 'committed'" @click="commit">发布报价</button>
      </div>
    </div>

    <div class="review-toolbar">
      <label><span>导入批次</span>
        <select v-model="selectedBatchId">
          <option v-for="batch in market.batches" :key="batch.id" :value="batch.id">
            #{{ batch.id }} · {{ batch.filename }} · {{ batch.total_candidates }} 条
          </option>
        </select>
      </label>
      <div class="review-stat"><span>当前页待复核</span><b>{{ pending }}</b></div>
      <div class="review-stat warning"><span>低置信度</span><b>{{ lowConfidence }}</b></div>
      <div class="review-stat"><span>全部候选</span><b>{{ total }}</b></div>
    </div>

    <div v-if="selectedBatch?.error_message" class="batch-warning">{{ selectedBatch.error_message }}</div>

    <div class="data-table-wrap" v-loading="loading">
      <table class="market-table">
        <thead><tr><th>来源</th><th>品牌 / 型号</th><th>规格</th><th>颜色 / 版本</th><th>价格</th><th>置信度</th><th>状态</th><th></th></tr></thead>
        <tbody>
          <tr v-for="row in candidates" :key="row.id" :class="{ uncertain: row.confidence < 0.75 }">
            <td><small>{{ row.sheet_name || '图片' }}</small><br><code>{{ row.cell_address || `L${row.id}` }}</code></td>
            <td><b>{{ row.brand }}</b><br><span>{{ row.model }}</span></td>
            <td>{{ row.storage || '—' }}</td>
            <td>{{ [row.color, row.variant].filter(Boolean).join(' · ') || '—' }}</td>
            <td><strong v-if="row.price_status === 'quoted'">¥{{ row.price }}</strong><span v-else class="price-state">{{ row.price_status }}</span></td>
            <td><span class="confidence"><i :style="{ width: `${row.confidence * 100}%` }"></i></span><small>{{ Math.round(row.confidence * 100) }}%</small></td>
            <td><span :class="['review-badge', row.review_status]">{{ statusLabel(row.review_status) }}</span></td>
            <td class="row-actions"><button @click="reviewOne(row, 'approved')">✓</button><button @click="reviewOne(row, 'rejected')">×</button><button @click="edit(row)">编辑</button></td>
          </tr>
          <tr v-if="!candidates.length"><td colspan="8" class="empty-cell">选择一个有候选记录的批次开始复核。</td></tr>
        </tbody>
      </table>
    </div>
    <el-pagination v-if="total > 100" v-model:current-page="page" :page-size="100" :total="total" layout="prev, pager, next, total" />

    <el-dialog v-model="dialogOpen" title="修正识别字段" width="680px">
      <div class="edit-grid">
        <label><span>品牌</span><input v-model="editing.brand" /></label>
        <label><span>型号</span><input v-model="editing.model" /></label>
        <label><span>容量</span><input v-model="editing.storage" /></label>
        <label><span>颜色</span><input v-model="editing.color" /></label>
        <label><span>版本</span><input v-model="editing.variant" /></label>
        <label><span>报价日期</span><input v-model="editing.quote_date" type="date" /></label>
        <label><span>价格状态</span><select v-model="editing.price_status"><option value="quoted">明确报价</option><option value="no_quote">暂无报价</option><option value="masked">价格遮挡</option></select></label>
        <label><span>价格</span><input v-model.number="editing.price" type="number" :disabled="editing.price_status !== 'quoted'" /></label>
        <label class="wide"><span>复核备注</span><textarea v-model="editing.review_note" rows="3"></textarea></label>
        <div class="raw-source wide"><small>识别原文</small><p>{{ editing.raw_text }}</p></div>
      </div>
      <template #footer><button class="ghost-action" @click="dialogOpen = false">取消</button><button class="primary-action compact" @click="saveEdit">保存并返回</button></template>
    </el-dialog>
  </section>
</template>

