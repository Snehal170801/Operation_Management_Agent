import { api } from '@/lib/api-client'
import type { CaseEvent, CaseListItem, CaseStatus, CreateCaseRequest, CreateCaseResponse } from './types'

export const casesApi = {
  list: () => api.get<CaseListItem[]>('/cases'),
  get: (caseId: string) => api.get<CaseStatus>(`/cases/${caseId}`),
  events: (caseId: string) => api.get<CaseEvent[]>(`/cases/${caseId}/events`),
  create: (body: CreateCaseRequest) => api.post<CreateCaseResponse>('/cases', body),
}
