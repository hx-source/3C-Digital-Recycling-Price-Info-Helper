<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import { init, use, type ECharts } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { ElMessage } from 'element-plus'
import { apiClient, errorMessage } from '../api'
import type { ForecastBacktest, ForecastPoint, PriceForecast } from '../types'

use([LineChart, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, CanvasRenderer])

const query = ref('')
const includeExternal = ref(true)
const loading = ref(false)
const result = ref<PriceForecast | null>(null)
const backtest = ref<ForecastBacktest | null>(null)
const chartEl = ref<HTMLDivElement | null>(null)
let chart: ECharts | null = null

const identity = computed(() => result.value
  ? [result.value.brand, result.value.model, result.value.storage, result.value.color, result.value.variant].filter(Boolean).join(' ')
  : '')
const mainForecast = computed(() => result.value?.forecasts.find(item => item.horizon_days === 3) || result.value?.forecasts[0] || null)

function money(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  return `¥${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`
}

function percent(value: number | null | undefined) {
  return value === null || value === undefined ? '等待样本' : `${(value * 100).toFixed(1)}%`
}

function directionLabel(value: ForecastPoint['direction']) {
  return value === 'up' ? '偏涨' : value === 'down' ? '偏跌' : '震荡'
}

function sourceTypeLabel(value: string) {
  return ({ official: '官方', ecommerce: '电商', secondhand: '二手', news: '资讯', other: '其他' } as Record<string, string>)[value] || '其他'
}

function renderChart() {
  if (!chartEl.value || !result.value) return
  chart ||= init(chartEl.value)
  const history = result.value.history.map(item => ({ date: item.quote_date, value: Number(item.price) }))
  const forecast = result.value.forecasts.map(item => ({ date: item.target_date, value: Number(item.predicted_price) }))
  const dates = [...history.map(item => item.date), ...forecast.map(item => item.date)]
  const historyData: Array<number | null> = dates.map(date => history.find(item => item.date === date)?.value ?? null)
  const forecastData: Array<number | null> = dates.map(date => forecast.find(item => item.date === date)?.value ?? null)
  const baseIndex = history.length - 1
  if (baseIndex >= 0) forecastData[baseIndex] = history.at(-1)?.value ?? null
  chart.setOption({
    animationDuration: 450,
    grid: { left: 58, right: 24, top: 42, bottom: 34 },
    legend: { top: 5, right: 12, itemWidth: 14, textStyle: { color: '#667382', fontSize: 10 } },
    tooltip: { trigger: 'axis', valueFormatter: (value: unknown) => money(Number(value)) },
    xAxis: { type: 'category', boundaryGap: false, data: dates, axisLabel: { color: '#778493', fontSize: 10 }, axisLine: { lineStyle: { color: '#d9e0e6' } } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: '#778493', fontSize: 10, formatter: (value: number) => `¥${value}` }, splitLine: { lineStyle: { color: '#edf0f3' } } },
    series: [
      { name: '历史报价', type: 'line', data: historyData, connectNulls: false, symbolSize: 5, lineStyle: { width: 2, color: '#273647' }, itemStyle: { color: '#273647' } },
      { name: '预测中位价', type: 'line', data: forecastData, connectNulls: true, symbol: 'diamond', symbolSize: 7, lineStyle: { width: 2, type: 'dashed', color: '#3478f6' }, itemStyle: { color: '#3478f6' }, markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: '#d9e0e6', type: 'dotted' }, data: [{ xAxis: result.value.base_date }] } },
    ],
  })
  chart.resize()
}

async function runForecast(value = query.value) {
  const text = value.trim()
  if (!text || loading.value) return
  query.value = text
  loading.value = true
  try {
    const data = await apiClient.priceForecast(text, includeExternal.value)
    result.value = data
    backtest.value = await apiClient.forecastBacktest(data.model_key)
    await nextTick()
    renderChart()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

function chooseAlternative(label: string) {
  runForecast(label)
}

const resizeChart = () => chart?.resize()
watch(result, () => nextTick(renderChart))
window.addEventListener('resize', resizeChart)
onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeChart)
  chart?.dispose()
})
</script>

<template>
  <section class="view-panel forecast-view" v-loading="loading">
    <div class="section-heading forecast-heading">
      <div><h2>未来报价研判</h2><p>以型号＋容量＋颜色为主规格，输出未来 1、3、7、10 天的方向、区间与依据。</p></div>
      <form class="forecast-search" @submit.prevent="runForecast()">
        <input v-model="query" placeholder="例如：红米 K80 12+256 黑色" />
        <label><input v-model="includeExternal" type="checkbox" /><span>包含公开市场信息</span></label>
        <button class="primary-action" :disabled="loading || !query.trim()">{{ loading ? '调查中' : '开始预测' }}</button>
      </form>
    </div>

    <div v-if="!result" class="forecast-empty">
      <div class="forecast-empty-mark"><i></i><i></i><i></i><i></i></div>
      <h3>输入一个已发布过至少两天报价的具体规格</h3>
      <p>系统先匹配内部历史，再按需检索官方、电商、二手和资讯来源；公开信息只作辅助，不会覆盖内部报价事实。</p>
      <div>
        <button @click="runForecast('红米 K80 12+256 黑色')">试查 红米 K80</button>
        <button @click="runForecast('OPPO A6i 8+128 黑')">试查 OPPO A6i</button>
      </div>
    </div>

    <div v-else class="forecast-workspace">
      <section class="forecast-main">
        <header class="forecast-identity">
          <div><span>当前匹配规格</span><h3>{{ identity }}</h3><p>基准日 {{ result.base_date }} · 当前价 {{ money(result.base_price) }} · {{ result.sample_count }} 个有效报价日</p></div>
          <div v-if="mainForecast" :class="['forecast-main-call', mainForecast.direction]">
            <small>未来 3 天判断</small><strong>{{ directionLabel(mainForecast.direction) }}</strong><em>{{ money(mainForecast.lower_price) }} — {{ money(mainForecast.upper_price) }}</em>
          </div>
        </header>

        <div class="forecast-periods">
          <article v-for="item in result.forecasts" :key="item.horizon_days" :class="item.direction">
            <header><span>{{ item.horizon_days }} 天</span><em>{{ item.target_date }}</em></header>
            <strong>{{ money(item.predicted_price) }}</strong>
            <p>{{ money(item.lower_price) }} — {{ money(item.upper_price) }}</p>
            <dl>
              <div><dt>涨</dt><dd class="up">{{ percent(item.up_probability) }}</dd></div>
              <div><dt>平</dt><dd>{{ percent(item.stable_probability) }}</dd></div>
              <div><dt>跌</dt><dd class="down">{{ percent(item.down_probability) }}</dd></div>
            </dl>
            <small>预测置信度 {{ percent(item.confidence) }}</small>
          </article>
        </div>

        <article class="forecast-chart-card">
          <header><div><h3>历史与预测轨迹</h3><p>虚线右侧为预测中位价；卡片中的上下限才是建议关注的价格区间。</p></div><span>最长 10 天</span></header>
          <div ref="chartEl" class="forecast-chart"></div>
        </article>
      </section>

      <aside class="forecast-evidence">
        <section class="forecast-explanation">
          <header><span>研判说明</span><em>{{ result.generated_by_model ? '本地模型已参与' : '仅内部历史' }}</em></header>
          <p>{{ result.explanation }}</p>
          <ul><li v-for="factor in result.factors" :key="factor">{{ factor }}</li></ul>
        </section>

        <section class="forecast-backtest">
          <header><span>历史回测</span><small>{{ backtest?.evaluated_count || 0 }} 个已到期预测</small></header>
          <dl>
            <div><dt>方向准确率</dt><dd>{{ percent(backtest?.direction_accuracy) }}</dd></div>
            <div><dt>区间命中率</dt><dd>{{ percent(backtest?.interval_hit_rate) }}</dd></div>
            <div><dt>平均误差</dt><dd>{{ money(backtest?.mean_absolute_error) }}</dd></div>
          </dl>
        </section>

        <section v-if="result.alternatives.length" class="forecast-alternatives">
          <header><span>其他匹配规格</span></header>
          <button v-for="item in result.alternatives" :key="item.model_key" @click="chooseAlternative(item.label)"><b>{{ item.label }}</b><small>{{ item.latest_date }} · {{ money(item.latest_price) }}</small></button>
        </section>

        <section class="forecast-signals">
          <header><span>公开信息依据</span><small>{{ result.external_signals.length }} 条</small></header>
          <div v-if="result.external_signals.length" class="forecast-signal-list">
            <a v-for="item in result.external_signals" :key="item.url" :href="item.url" target="_blank" rel="noopener noreferrer">
              <em>{{ sourceTypeLabel(item.source_type) }}</em><b>{{ item.title }}</b><small>{{ item.source_domain || '公开网页' }} ↗</small>
            </a>
          </div>
          <p v-else class="forecast-no-signal">本次没有取得可用公开网页，预测仍可依据内部历史运行。</p>
        </section>
      </aside>
    </div>
  </section>
</template>
