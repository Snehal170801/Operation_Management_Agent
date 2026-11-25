import { api, ApiError } from '@/lib/api-client'
import type { Delivery } from './types'

export const deliveryApi = {
  /** null (not an error) when there is no purchase order to deliver yet. */
  get: async (caseId: string): Promise<Delivery | null> => {
    try {
      return await api.get<Delivery>(`/cases/${caseId}/delivery`)
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null
      throw error
    }
  },
  // Who received it comes from the signed-in session on the server.
  confirmReceived: (caseId: string, note?: string, items?: Record<string, number>) =>
    api.post<Delivery>(`/cases/${caseId}/delivery/received`, { note, items }),
  /** The supplier will not send the rest: accept the order as delivered with what has arrived. */
  shortClose: (caseId: string, note?: string) => api.post<Delivery>(`/cases/${caseId}/delivery/short-close`, { note }),
}
