<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiClient, errorMessage } from '../api'
import type { MarketMonitorFinding, MarketMonitorRun } from '../types'

const emit = defineEmits<{ navigate: [view: 'review'] }>()

const runs = ref<MarketMonitorRun[]>([])
const selectedId = ref('')
const loading = ref(false)
const severity = ref('all')
const findingType = ref('all')
const handlingStatus = ref('active')
const selectedFinding = ref<MarketMonitorFinding | null>(null)
const drawerOpen = ref(false)
const diagnosing = ref(false)
const applying = ref(false)
const selected = computed(() => runs.value.find(item => item.id === selectedId.value) || runs.value[0] || null)
const types = computed(() => [...new Set(selected.value?.findings.map(item => item.finding_type) || [])])
const findings = computed(() => (selected.value?.findings || []).filter(item =>
  (severity.value === 'all' || item.severity === severity.value)
  && (findingType.value === 'all' || item.finding_type === findingType.value)
  && (handlingStatus.value === 'all' || (handlingStatus.value === 'active'
    ? ['open', 'diagnosed'].includes(item.handling_status)
    : item.handling_status === handlingStatus.value))))

function triggerLabel(value: string) {
  return { publish: '发布触发', manual: '手动触发', remediation: '修正后复检' }[value] || value
}

function handlingLabel(value: string) {
  return { open: '待诊断', diagnosed: '待确认', resolved: '已修正', dismissed: '已忽略' }[value] || value
}

function updateFinding(updated: MarketMonitorFinding) {
  const run = selected.value
  if (!run) return
  const index = run.findings.findIndex(item => item.id === updated.id)
  if (index >= 0) run.findings[index] = updated
  selectedFinding.value = updated
}

async function openFinding(item: MarketMonitorFinding) {
  selectedFinding.value = item
  drawerOpen.value = true
}

async function diagnoseSelected() {
  if (!selectedFinding.value) return
  diagnosing.value = true
  try {
    updateFinding(await apiClient.diagnoseMonitorFinding(selectedFinding.value.id))
    ElMessage.success('诊断完成，请核对证据和建议')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    diagnosing.value = false
  }
}

async function applySelected() {
  const item = selectedFinding.value
  if (!item || (!item.proposed_price && !item.proposed_price_status)) return
  const actionText = item.proposed_price_status === 'masked'
    ? '将该记录恢复为“价格区间/掩码”，不再参与精确涨跌计算'
    : `将已发布价格修正为 ${Number(item.proposed_price).toFixed(0)} 元，并同步原候选记录`
  try {
    const { value } = await ElMessageBox.prompt(
      `${actionText}。修正后会自动重新监控。`,
      '人工确认执行',
      { confirmButtonText: '确认修正', cancelButtonText: '取消', inputPlaceholder: '可填写确认依据或备注' },
    )
    applying.value = true
    updateFinding(await apiClient.applyMonitorFinding(item.id, item.proposed_price, item.proposed_price_status, value))
    ElMessage.success('修正已执行，复检任务已启动')
    await loadRuns()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorMessage(error))
  } finally {
    applying.value = false
  }
}

async function dismissSelected() {
  const item = selectedFinding.value
  if (!item) return
  try {
    const { value } = await ElMessageBox.prompt('确认该异常是真实行情或无需处理后，可将其移出待办。', '忽略异常', {
      confirmButtonText: '确认忽略', cancelButtonText: '取消', inputPlaceholder: '填写判断依据（可选）',
    })
    updateFinding(await apiClient.dismissMonitorFinding(item.id, value))
    ElMessage.success('已标记为无需处理')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorMessage(error))
  }
}

function statusLabel(status: string) {
  return { queued: '等待执行', running: '正在监控', completed: '监控完成', failed: '运行失败' }[status] || status
}

function timeLabel(value: string) {
  return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function loadRuns(preferredId?: string) {
  runs.value = await apiClient.monitorRuns()
  selectedId.value = preferredId && runs.value.some(item => item.id === preferredId) ? preferredId : selectedId.value || runs.value[0]?.id || ''
}

async function runMonitor() {
  loading.value = true
  try {
    let run = await apiClient.startMonitorRun()
    selectedId.value = run.id
    while (['queued', 'running'].includes(run.status)) {
      await new Promise(resolve => window.setTimeout(resolve, 800))
      run = await apiClient.monitorRun(run.id)
      const index = runs.value.findIndex(item => item.id === run.id)
      if (index >= 0) runs.value[index] = run
      else runs.value.unshift(run)
    }
    await loadRuns(run.id)
    if (run.status === 'completed') ElMessage.success(`监控完成，发现 ${run.finding_count} 项关注点`)
    else ElMessage.error(run.error_message || '监控任务执行失败')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try { await loadRuns() } catch (error) { ElMessage.error(errorMessage(error)) } finally { loading.value = false }
})
</script>

<template>
  <section class="view-panel monitor-view">
    <div class="section-heading monitor-heading">
      <div><h2>行情监控智能体</h2><p>发布后自动比较上期行情，主动发现价格、结构和数据完整性风险。</p></div>
      <button class="primary-action compact" :disabled="loading" @click="runMonitor">{{ loading ? '监控运行中…' : '立即运行监控' }}</button>
    </div>
    <div class="monitor-layout">
      <aside class="monitor-run-panel">
        <header><strong>监控记录</strong><small>发布后自动生成</small></header>
        <div class="monitor-run-list">
          <button v-for="run in runs" :key="run.id" :class="{ active: run.id === selectedId }" @click="selectedId = run.id">
            <i :class="run.status"></i><span><b>{{ run.quote_date || '等待行情' }}</b><small>{{ timeLabel(run.created_at) }} · {{ triggerLabel(run.trigger_type) }}</small></span><em>{{ statusLabel(run.status) }}</em>
          </button>
          <p v-if="!runs.length">还没有监控记录。</p>
        </div>
      </aside>
      <main v-if="selected" class="monitor-report">
        <section class="monitor-summary">
          <div><small>监控日报 · {{ selected.quote_date || '—' }}</small><strong>{{ statusLabel(selected.status) }}</strong><p>{{ selected.summary || selected.error_message || '智能体正在读取报价、对比上期并生成简报…' }}</p><em>{{ selected.generated_by_model ? `本地模型 ${selected.model_name} 已参与总结` : '检测结果来自确定性工具' }}</em></div>
          <dl><div><dt>扫描报价</dt><dd>{{ selected.scanned_quotes }}</dd></div><div><dt>关注项</dt><dd>{{ selected.finding_count }}</dd></div><div class="danger"><dt>高风险</dt><dd>{{ selected.danger_count }}</dd></div><div class="warning"><dt>需关注</dt><dd>{{ selected.warning_count }}</dd></div></dl>
        </section>
        <section class="monitor-workflow"><span>智能体工作流</span><ol><li class="done"><i>1</i><b>读取最新行情</b></li><li :class="{ done: selected.status !== 'queued' }"><i>2</i><b>跨期与结构检测</b></li><li :class="{ done: selected.status === 'completed' }"><i>3</i><b>综合风险简报</b></li></ol></section>
        <div class="monitor-filters"><select v-model="handlingStatus"><option value="active">待处理</option><option value="all">全部状态</option><option value="resolved">已修正</option><option value="dismissed">已忽略</option></select><select v-model="severity"><option value="all">全部风险</option><option value="danger">高风险</option><option value="warning">需关注</option><option value="info">信息</option></select><select v-model="findingType"><option value="all">全部类型</option><option v-for="item in types" :key="item" :value="item">{{ item }}</option></select><span>{{ findings.length }} 项结果</span></div>
        <div class="monitor-findings">
          <article v-for="item in findings" :key="item.id" :class="[item.severity, 'actionable']" @click="openFinding(item)"><i></i><div><small>{{ item.finding_type }}<template v-if="item.brand"> · {{ item.brand }}</template><em :class="item.handling_status">{{ handlingLabel(item.handling_status) }}</em></small><strong>{{ item.title }}</strong><p>{{ item.detail }}</p></div><button type="button">处置 →</button></article>
          <p v-if="selected.status === 'completed' && !findings.length" class="monitor-empty">当前筛选没有异常发现。</p>
        </div>
      </main>
      <main v-else class="monitor-report monitor-empty">发布一批报价或点击“立即运行监控”后，这里会生成行情日报。</main>
    </div>

    <el-drawer v-model="drawerOpen" title="异常处置智能体" size="min(520px, 94vw)" class="remediation-drawer" @closed="selectedFinding = null">
      <template v-if="selectedFinding">
        <section class="remediation-title"><span>{{ selectedFinding.finding_type }} · {{ handlingLabel(selectedFinding.handling_status) }}</span><h3>{{ selectedFinding.title }}</h3><p>{{ selectedFinding.detail }}</p></section>
        <section class="remediation-evidence"><header><strong>已掌握的证据</strong><small>只基于系统数据</small></header><dl><div v-for="(value, key) in selectedFinding.evidence" :key="key"><dt>{{ { previous_price: '上一期价格', current_price: '当前价格', change_amount: '涨跌额', source_text: '来源原文', source_position: '来源位置', price_ratio: '价格比例', candidate_id: '候选记录', current_quote_id: '报价记录', reason_code: '判断依据', suggested_status: '建议状态', count: '涉及数量', spread: '价格差值' }[key] || key }}</dt><dd>{{ value || '—' }}</dd></div></dl></section>
        <section v-if="selectedFinding.diagnosis" class="remediation-result"><header><strong>智能诊断</strong><em>{{ Math.round((selectedFinding.diagnosis_confidence || 0) * 100) }}% 可信</em></header><p>{{ selectedFinding.diagnosis }}</p><h4>建议</h4><p>{{ selectedFinding.recommendation }}</p><div v-if="selectedFinding.proposed_price" class="proposed-price"><span>建议修正价格</span><strong>¥ {{ Number(selectedFinding.proposed_price).toFixed(0) }}</strong></div><div v-else-if="selectedFinding.proposed_price_status === 'masked'" class="proposed-price"><span>建议价格状态</span><strong>价格区间/掩码</strong></div></section>
        <section v-if="selectedFinding.handled_reason" class="remediation-handled"><strong>{{ handlingLabel(selectedFinding.handling_status) }}</strong><p>{{ selectedFinding.handled_reason }}</p></section>
        <footer class="remediation-actions">
          <button v-if="selectedFinding.handling_status === 'open'" class="primary-action" :disabled="diagnosing" @click="diagnoseSelected">{{ diagnosing ? '正在调查…' : '启动智能诊断' }}</button>
          <button v-if="selectedFinding.handling_status === 'diagnosed' && (selectedFinding.proposed_price || selectedFinding.proposed_price_status)" class="primary-action" :disabled="applying" @click="applySelected">确认采用建议</button>
          <button v-if="['open', 'diagnosed'].includes(selectedFinding.handling_status)" class="ghost-action" @click="dismissSelected">确认无需处理</button>
          <button v-if="selectedFinding.quote_id" class="ghost-action" @click="emit('navigate', 'review')">前往复核工作台</button>
        </footer>
      </template>
    </el-drawer>
  </section>
</template>
