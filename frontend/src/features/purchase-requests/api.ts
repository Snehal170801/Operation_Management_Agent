import { api } from '@/lib/api-client'
import type { PurchaseRequest } from './types'

export const purchaseRequestsApi = {
  getByCase: (caseId: string) => api.get<PurchaseRequest>(`/purchase-requests/${caseId}`),
}
