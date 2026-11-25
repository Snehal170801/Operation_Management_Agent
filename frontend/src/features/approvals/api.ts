import { api } from '@/lib/api-client'
import type { Approval, ApprovalReview } from './types'

export const approvalsApi = {
  list: (status?: string, caseId?: string) => {
    const params = new URLSearchParams()
    if (status) params.set('status', status)
    if (caseId) params.set('case_id', caseId)
    const query = params.toString()
    return api.get<Approval[]>(`/approvals${query ? `?${query}` : ''}`)
  },
  // Who decided comes from the signed-in session on the server, not from this request.
  /** Everything needed to decide: the request, every supplier's reply, the AI's ranking and reasons. */
  review: (approvalId: string) => api.get<ApprovalReview>(`/approvals/${approvalId}/review`),
  // `vendorId` is the supplier the person chose (the AI's pick unless they changed it).
  approve: (approvalId: string, note?: string, vendorId?: string) => api.post<Approval>(`/approvals/${approvalId}/approve`, { note, vendor_id: vendorId }),
  // `reSource` sends the request back out for new quotes instead of ending it; `skipSelected` leaves the chosen supplier out.
  reject: (approvalId: string, note?: string, reSource = false, skipSelected = false) =>
    api.post<Approval>(`/approvals/${approvalId}/reject`, { note, re_source: reSource, skip_selected: skipSelected }),
}
