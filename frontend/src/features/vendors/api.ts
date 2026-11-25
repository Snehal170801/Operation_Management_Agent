import { api } from '@/lib/api-client'
import type { Quote, Rfq, SubmitQuoteRequest, UpdateVendorRequest, UpsertVendorRequest, Vendor, VendorSelection } from './types'

export const vendorsApi = {
  list: () => api.get<Vendor[]>('/vendors'),
  upsert: (body: UpsertVendorRequest) => api.post<void>('/vendors', body),
  update: (id: string, body: UpdateVendorRequest) => api.put<void>(`/vendors/${id}`, body),
  rfqs: (caseId: string) => api.get<Rfq[]>(`/cases/${caseId}/rfqs`),
  quotes: (caseId: string) => api.get<Quote[]>(`/cases/${caseId}/quotes`),
  submitQuote: (caseId: string, body: SubmitQuoteRequest) =>
    api.post<Quote>(`/cases/${caseId}/quotes`, body),
  rank: (caseId: string) => api.post<VendorSelection>(`/cases/${caseId}/rank-vendors`),
  selection: (caseId: string) => api.get<VendorSelection>(`/cases/${caseId}/vendor-selection`),
}
