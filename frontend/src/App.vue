<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, ref, watch } from 'vue'
import { useMarketStore } from './stores/market'

type ViewName = 'agent' | 'forecast' | 'monitor' | 'dashboard' | 'import' | 'review' | 'quotes'

const active = ref<ViewName>('agent')
const market = useMarketStore()
const contentViewport = ref<HTMLElement | null>(null)

const views = {
  agent: defineAsyncComponent(() => import('./views/AgentView.vue')),
  forecast: defineAsyncComponent(() => import('./views/ForecastView.vue')),
  monitor: defineAsyncComponent(() => import('./views/MonitorView.vue')),
  dashboard: defineAsyncComponent(() => import('./views/DashboardView.vue')),
  import: defineAsyncComponent(() => import('./views/ImportView.vue')),
  review: defineAsyncComponent(() => import('./views/ReviewView.vue')),
  quotes: defineAsyncComponent(() => import('./views/QuotesView.vue')),
}
const activeComponent = computed(() => views[active.value])
const viewTitle = computed(() => ({
  agent: '行情智能体',
  forecast: '价格预测',
  monitor: '行情监控智能体',
  dashboard: '市场概览',
  import: '数据来源导入智能体',
  review: '复核工作台',
  quotes: '报价历史',
})[active.value])

const navItems: Array<{ key: ViewName; label: string; mark: string }> = [
  { key: 'agent', label: '智能问答', mark: '✦' },
  { key: 'forecast', label: '价格预测', mark: '⌁' },
  { key: 'monitor', label: '行情监控', mark: '◎' },
  { key: 'dashboard', label: '市场概览', mark: '◫' },
  { key: 'import', label: '来源导入', mark: '↥' },
  { key: 'review', label: '复核工作台', mark: '✓' },
  { key: 'quotes', label: '报价历史', mark: '↗' },
]

watch(active, async () => {
  await nextTick()
  contentViewport.value?.scrollTo({ top: 0, behavior: 'smooth' })
})

onMounted(() => market.refresh())
</script>

<template>
  <div class="app-shell">
    <aside class="side-rail">
      <button class="brand-lockup" @click="active = 'dashboard'">
        <span class="brand-mark"><i></i><i></i><i></i></span>
        <span><strong>回收雷达</strong></span>
      </button>

      <nav class="nav-stack" aria-label="主导航">
        <button
          v-for="item in navItems"
          :key="item.key"
          :class="['nav-item', { active: active === item.key }]"
          @click="active = item.key"
        >
          <span class="nav-mark">{{ item.mark }}</span>
          <span>{{ item.label }}</span>
        </button>
      </nav>

    </aside>

    <main :class="['main-stage', { 'agent-stage': active === 'agent', 'forecast-stage': active === 'forecast' }]">
      <header class="topbar">
        <div class="topbar-title"><span class="topbar-rail"></span><h1>{{ viewTitle }}</h1></div>
        <div class="date-stamp">
          <small>最新报价日</small>
          <strong>{{ market.dashboard?.latest_quote_date || '待发布' }}</strong>
        </div>
      </header>

      <div ref="contentViewport" :class="['content-viewport', { 'agent-viewport': active === 'agent', 'forecast-viewport': active === 'forecast' }]">
        <component :is="activeComponent" @navigate="(view: ViewName) => (active = view)" />
      </div>
    </main>
  </div>
</template>
