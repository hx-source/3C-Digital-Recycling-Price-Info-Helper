<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiClient, errorMessage } from '../api'
import type { PriceChange, Quote } from '../types'

const tab = ref<'changes' | 'history'>('changes')
const search = ref('')
const changes = ref<PriceChange[]>([])
const quotes = ref<Quote[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const [changeRows, quoteRows] = await Promise.all([apiClient.changes(search.value), apiClient.quotes(1, 200, search.value)])
    changes.value = changeRows
    quotes.value = quoteRows.items
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

function signed(value: number | null) {
  if (value === null) return '首次报价'
  return `${value > 0 ? '+' : ''}${value}`
}

function priceStatusLabel(status: string) {
  return { quoted: '明确报价', no_quote: '暂无报价', masked: '价格遮挡' }[status] || status
}

onMounted(load)
</script>

<template>
  <section class="view-panel quotes-view" v-loading="loading">
    <div class="section-heading">
      <div><h2>每一笔变化都有来源</h2></div>
      <div class="search-box"><input v-model="search" placeholder="搜索型号、容量或颜色" @keyup.enter="load" /><button @click="load">搜索</button></div>
    </div>

    <div class="tab-switch"><button :class="{ active: tab === 'changes' }" @click="tab = 'changes'">涨跌比较</button><button :class="{ active: tab === 'history' }" @click="tab = 'history'">报价流水</button></div>

    <div class="data-table-wrap ledger-scroll">
      <table v-if="tab === 'changes'" class="market-table change-table">
        <thead><tr><th>型号</th><th>规格</th><th>本期</th><th>上期</th><th>涨跌额</th><th>涨跌幅</th><th>日期</th></tr></thead>
        <tbody>
          <tr v-for="row in changes" :key="row.model_key" :class="{ abnormal: row.requires_review }">
            <td><b>{{ row.brand }}</b><br><span>{{ row.model }} {{ row.color || '' }}</span></td>
            <td>{{ row.storage || '—' }}<small v-if="row.variant">{{ row.variant }}</small></td>
            <td><strong>¥{{ row.current_price }}</strong></td>
            <td>{{ row.previous_price === null ? '—' : `¥${row.previous_price}` }}</td>
            <td><em :class="(row.change_amount || 0) >= 0 ? 'up' : 'down'">{{ signed(row.change_amount) }}</em><small v-if="row.requires_review" class="abnormal-flag">异常待复核</small></td>
            <td>{{ row.change_percent === null ? '—' : `${signed(row.change_percent)}%` }}</td>
            <td>{{ row.current_date }}<small v-if="row.previous_date">对比 {{ row.previous_date }}</small></td>
          </tr>
          <tr v-if="!changes.length"><td colspan="7" class="empty-cell">至少发布两期相同型号、规格、颜色的明确报价后可比较。</td></tr>
        </tbody>
      </table>

      <table v-else class="market-table">
        <thead><tr><th>日期</th><th>来源</th><th>分类</th><th>品牌 / 型号</th><th>规格</th><th>颜色 / 版本</th><th>报价状态</th><th>价格</th></tr></thead>
        <tbody>
          <tr v-for="row in quotes" :key="row.id">
            <td>{{ row.quote_date }}</td><td>{{ row.source_name }}</td><td>{{ row.category }}</td>
            <td><b>{{ row.brand }}</b><br>{{ row.model }}</td><td>{{ row.storage || '—' }}</td>
            <td>{{ [row.color, row.variant].filter(Boolean).join(' · ') || '—' }}</td>
            <td><span class="price-state">{{ priceStatusLabel(row.price_status) }}</span></td><td><strong>{{ row.price === null ? '—' : `¥${row.price}` }}</strong></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
