import { defineStore } from 'pinia'
import { apiClient } from '../api'
import type { Batch, DashboardSummary, PriceChange } from '../types'

export const useMarketStore = defineStore('market', {
  state: () => ({
    dashboard: null as DashboardSummary | null,
    batches: [] as Batch[],
    changes: [] as PriceChange[],
    loading: false,
  }),
  actions: {
    async refresh() {
      this.loading = true
      try {
        const [dashboard, batches, changes] = await Promise.all([
          apiClient.dashboard(),
          apiClient.batches(),
          apiClient.changes(),
        ])
        this.dashboard = dashboard
        this.batches = batches
        this.changes = changes
      } finally {
        this.loading = false
      }
    },
  },
})

