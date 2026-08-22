<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, ref, watch } from 'vue'
import { useMarketStore } from './stores/market'

type ViewName = 'dashboard' | 'import' | 'review' | 'quotes'

const active = ref<ViewName>('dashboard')
const market = useMarketStore()

const views = {
  dashboard: defineAsyncComponent(() => import('./views/DashboardView.vue')),
  import: defineAsyncComponent(() => import('./views/ImportView.vue')),
  review: defineAsyncComponent(() => import('./views/ReviewView.vue')),
  quotes: defineAsyncComponent(() => import('./views/QuotesView.vue')),
}
const activeComponent = computed(() => views[active.value])

const navItems: Array<{ key: ViewName; label: string; caption: string }> = [
  { key: 'dashboard', label: '市场概览', caption: 'MARKET' },
  { key: 'import', label: '数据导入', caption: 'INGEST' },
  { key: 'review', label: '复核工作台', caption: 'REVIEW' },
  { key: 'quotes', label: '报价历史', caption: 'LEDGER' },
]

watch(active, async () => {
  await nextTick()
  window.scrollTo({ top: 0, behavior: 'smooth' })
})

onMounted(() => market.refresh())
</script>

<template>
  <div class="app-shell">
    <aside class="side-rail">
      <button class="brand-lockup" @click="active = 'dashboard'">
        <span class="brand-mark"><i></i><i></i><i></i></span>
        <span><strong>PriceRadar</strong><small>3C 回收行情台</small></span>
      </button>

      <nav class="nav-stack" aria-label="主导航">
        <button
          v-for="item in navItems"
          :key="item.key"
          :class="['nav-item', { active: active === item.key }]"
          @click="active = item.key"
        >
          <span class="nav-caption">{{ item.caption }}</span>
          <span>{{ item.label }}</span>
        </button>
      </nav>

      <div class="system-status">
        <span class="live-dot"></span>
        <div><small>数据链路</small><strong>ONLINE</strong></div>
      </div>
    </aside>

    <main class="main-stage">
      <header class="topbar">
        <div>
          <p class="eyebrow">ZHENGZHOU · DAILY BUYBACK INTELLIGENCE</p>
          <h1>把每日报价，变成可比较的市场信号。</h1>
        </div>
        <div class="date-stamp">
          <small>最新行情日</small>
          <strong>{{ market.dashboard?.latest_quote_date || '待发布' }}</strong>
        </div>
      </header>

      <section class="pulse-track" aria-label="数据处理流程">
        <div class="pulse-line"></div>
        <div class="pulse-node done"><span>01</span><strong>上传来源</strong><small>Excel / 图片</small></div>
        <div class="pulse-node"><span>02</span><strong>结构识别</strong><small>拆分型号与报价</small></div>
        <div class="pulse-node"><span>03</span><strong>人工复核</strong><small>{{ market.dashboard?.pending_candidates || 0 }} 条待处理</small></div>
        <div class="pulse-node"><span>04</span><strong>行情发布</strong><small>{{ market.dashboard?.published_quotes || 0 }} 条历史</small></div>
      </section>

      <component :is="activeComponent" @navigate="(view: ViewName) => (active = view)" />
    </main>
  </div>
</template>
