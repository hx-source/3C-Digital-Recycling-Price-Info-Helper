<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { init, use, type ECharts } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useMarketStore } from '../stores/market'

use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

defineEmits<{ navigate: [view: 'import' | 'review' | 'quotes'] }>()

const market = useMarketStore()
const chartEl = ref<HTMLDivElement | null>(null)
let chart: ECharts | null = null

const tape = computed(() => market.changes.filter(item => item.change_amount !== null).slice(0, 12))

function renderChart() {
  if (!chartEl.value || !market.dashboard) return
  chart ||= init(chartEl.value)
  const rows = [...market.dashboard.top_decreases.slice(0, 5).reverse(), ...market.dashboard.top_increases.slice(0, 5)]
  chart.setOption({
    grid: { left: 120, right: 30, top: 18, bottom: 24 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#d7dee5' } },
      splitLine: { lineStyle: { color: '#edf0f3' } },
      axisLabel: { color: '#667382' },
    },
    yAxis: {
      type: 'category',
      data: rows.map(item => `${item.model} ${item.storage || ''} ${item.color || ''}`),
      axisLabel: { color: '#26313d', width: 110, overflow: 'truncate' },
      axisTick: { show: false },
      axisLine: { show: false },
    },
    series: [{
      type: 'bar',
      data: rows.map(item => ({
        value: item.change_amount,
        itemStyle: { color: (item.change_amount || 0) >= 0 ? '#e33f32' : '#27916b', borderRadius: [2, 2, 2, 2] },
      })),
      barWidth: 12,
    }],
  })
}

watch(() => market.dashboard, () => nextTick(renderChart), { deep: true })
onMounted(() => {
  nextTick(renderChart)
  window.addEventListener('resize', () => chart?.resize())
})
</script>

<template>
  <section class="view-panel dashboard-view" v-loading="market.loading">
    <div class="section-heading">
      <div><p class="eyebrow">TODAY'S SIGNAL</p><h2>行情变化一眼看清</h2></div>
      <button class="text-action" @click="$emit('navigate', 'quotes')">查看完整报价 →</button>
    </div>

    <div class="metric-strip">
      <article><span>已发布报价</span><strong>{{ market.dashboard?.published_quotes || 0 }}</strong><small>累计有效历史</small></article>
      <article class="signal-up"><span>上涨型号</span><strong>{{ market.dashboard?.today_increases || 0 }}</strong><small>相对上次有效报价</small></article>
      <article class="signal-down"><span>下跌型号</span><strong>{{ market.dashboard?.today_decreases || 0 }}</strong><small>仅统计明确价格</small></article>
      <article class="signal-warn"><span>待复核</span><strong>{{ market.dashboard?.pending_candidates || 0 }}</strong><small>确认后进入历史库</small></article>
    </div>

    <div class="dashboard-grid">
      <article class="chart-card">
        <div class="card-title"><span>PRICE DELTA</span><h3>本期涨跌额分布</h3></div>
        <div ref="chartEl" class="delta-chart"></div>
      </article>
      <article class="action-card">
        <div class="card-title"><span>NEXT ACTION</span><h3>今日处理队列</h3></div>
        <button @click="$emit('navigate', 'import')"><b>01</b><span><strong>导入新报价</strong><small>支持 Excel 与图片</small></span><i>↗</i></button>
        <button @click="$emit('navigate', 'review')"><b>02</b><span><strong>复核识别结果</strong><small>{{ market.dashboard?.pending_candidates || 0 }} 条等待处理</small></span><i>↗</i></button>
        <button @click="$emit('navigate', 'quotes')"><b>03</b><span><strong>查看价格历史</strong><small>定位异常涨跌</small></span><i>↗</i></button>
      </article>
    </div>

    <div class="ticker-board">
      <div class="ticker-label"><span>LIVE</span><strong>价格脉冲</strong></div>
      <div class="ticker-flow" v-if="tape.length">
        <span v-for="item in tape" :key="item.model_key">
          {{ item.model }} {{ item.color || '' }}
          <b>¥{{ item.current_price }}</b>
          <em :class="(item.change_amount || 0) >= 0 ? 'up' : 'down'">
            {{ (item.change_amount || 0) > 0 ? '+' : '' }}{{ item.change_amount }}
          </em>
        </span>
      </div>
      <div class="ticker-empty" v-else>发布两期相同型号报价后，这里会出现实时涨跌。</div>
    </div>
  </section>
</template>
