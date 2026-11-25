import { api, ApiError } from '@/lib/api-client'
import type { PurchaseOrder, PurchaseOrderListItem } from './types'

export const purchaseOrdersApi = {
  list: () => api.get<PurchaseOrderListItem[]>('/purchase-orders'),
  /** null (not an error) when no purchase order has been issued for the case yet. */
  get: async (caseId: string): Promise<PurchaseOrder | null> => {
    try {
      return await api.get<PurchaseOrder>(`/cases/${caseId}/purchase-order`)
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null
      throw error
    }
  },
  /** Retry issuing / re-sending the purchase order. Safe to repeat: one PO per case. */
  issue: (caseId: string) => api.post<PurchaseOrder>(`/cases/${caseId}/purchase-order`),
  /** A person records that the supplier confirmed the order another way, or that a problem they raised is sorted out. */
  confirm: (caseId: string, note?: string) => api.post<PurchaseOrder>(`/cases/${caseId}/purchase-order/confirmed`, { note }),
}
