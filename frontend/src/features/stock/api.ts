import { api } from '@/lib/api-client'
import type { ReorderRequest, ReorderResponse, StockHistoryEntry, StockItem, StockLevelsRequest, UpdateStockItemRequest, UpsertStockRequest } from './types'

export const stockApi = {
  list: () => api.get<StockItem[]>('/stock'),
  history: (item: string) => api.get<StockHistoryEntry[]>(`/stock/history?item=${encodeURIComponent(item)}`),
  upsert: (body: UpsertStockRequest) => api.post<void>('/stock', body),
  updateItem: (body: UpdateStockItemRequest) => api.patch<void>('/stock/item', body),
  removeItem: (item: string) => api.delete<void>(`/stock/item?item=${encodeURIComponent(item)}`),
  setLevels: (body: StockLevelsRequest) => api.put<void>('/stock/levels', body),
  reorder: (body: ReorderRequest) => api.post<ReorderResponse>('/stock/reorder', body),
}
