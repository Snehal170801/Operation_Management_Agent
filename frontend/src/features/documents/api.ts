import { api } from '@/lib/api-client'
import type { UnmatchedDocument } from './types'

export const documentsApi = {
  list: () => api.get<UnmatchedDocument[]>('/documents/unmatched'),
  attach: (id: string, caseId: string) => api.post<{ outcome: string }>(`/documents/unmatched/${id}/attach`, { case_id: caseId }),
  dismiss: (id: string, note?: string) => api.post<void>(`/documents/unmatched/${id}/dismiss`, { note }),
}
