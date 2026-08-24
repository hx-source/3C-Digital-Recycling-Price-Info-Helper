<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, ref, watch } from 'vue'
import { useMarketStore } from './stores/market'

type ViewName = 'dashboard' | 'import' | 'review' | 'quotes'

const active = ref<ViewName>('dashboard')
const market = useMarketStore()
const contentViewport = ref<HTMLElement | null>(null)

const views = {
  dashboard: defineAsyncComponent(() => import('./views/DashboardView.vue')),
  import: defineAsyncComponent(() => import('./views/ImportView.vue')),
  review: defineAsyncComponent(() => import('./views/ReviewView.vue')),
  quotes: defineAsyncComponent(() => import('./views/QuotesView.vue')),
}
const activeComponent = computed(() => views[active.value])

const navItems: Array<{ key: ViewName; label: string; caption: string; mark: string }> = [
  { key: 'dashboard', label: '市场概览', caption: 'MARKET', mark: '◫' },
  { key: 'import', label: '数据导入', caption: 'INGEST', mark: '↥' },
  { key: 'review', label: '复核工作台', caption: 'REVIEW', mark: '✓' },
  { key: 'quotes', label: '报价历史', caption: 'LEDGER', mark: '↗' },
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
        <span><strong>回收雷达</strong><small>3C PRICE DESK</small></span>
      </button>

      <nav class="nav-stack" aria-label="主导航">
        <button
          v-for="item in navItems"
          :key="item.key"
          :class="['nav-item', { active: active === item.key }]"
          @click="active = item.key"
        >
          <span class="nav-mark">{{ item.mark }}</span>
          <span><small class="nav-caption">{{ item.caption }}</small>{{ item.label }}</span>
        </button>
      </nav>

      <div class="system-status">
        <span class="live-dot"></span>
        <div><small>数据链路</small><strong>ONLINE</strong></div>
      </div>
    </aside>

    <main class="main-stage">
      <header class="topbar">
        <div class="topbar-title"><span class="topbar-rail"></span><h1>行情工作台</h1><small>DAILY BUYBACK DESK</small></div>
        <div class="date-stamp">
          <small>最新报价日</small>
          <strong>{{ market.dashboard?.latest_quote_date || '待发布' }}</strong>
        </div>
      </header>

      <div ref="contentViewport" class="content-viewport">
        <component :is="activeComponent" @navigate="(view: ViewName) => (active = view)" />
      </div>
    </main>
  </div>
</template>
