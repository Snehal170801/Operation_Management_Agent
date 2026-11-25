import { api } from '@/lib/api-client'
import type { Invoice } from './types'

export const invoicesApi = {
  list: (status?: string) => api.get<Invoice[]>(`/invoices${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  forCase: (caseId: string) => api.get<Invoice[]>(`/cases/${caseId}/invoices`),
  /** Paste the invoice text; the agent reads it and matches it against the order and the receipt. */
  submit: (caseId: string, rawText: string) => api.post<Invoice>(`/cases/${caseId}/invoices`, { raw_text: rawText }),
  // Who decided comes from the signed-in session on the server.
  approve: (invoiceId: string, note?: string) => api.post<Invoice>(`/invoices/${invoiceId}/approve`, { note }),
  reject: (invoiceId: string, note?: string) => api.post<Invoice>(`/invoices/${invoiceId}/reject`, { note }),
}
