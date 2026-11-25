import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api-client'

export type IssueKind = 'damaged' | 'wrong_item' | 'not_as_described' | 'other'

export const KIND_LABEL: Record<IssueKind, string> = {
  damaged: 'Arrived damaged',
  wrong_item: 'Not what was ordered',
  not_as_described: 'Does not match the specification',
  other: 'Something else',
}

export interface GoodsIssue {
  issue_id: string
  case_id: string
  po_number: string
  vendor_name: string
  kind: IssueKind
  items: { description: string; quantity: number }[]
  description: string | null
  reported_by: string
  reported_at: string
  status: 'open' | 'resolved'
  supplier_told_at: string | null
  supplier_replied_at: string | null
  chase_count: number
  escalated_at: string | null
  resolution: 'replaced' | 'credit' | 'accepted' | null
  credit_amount: number | null
  resolution_note: string | null
  resolved_by: string | null
  resolved_at: string | null
  /** Sending the goods back and waiting for a replacement (tracking only: nothing owed changes). */
  return_status: 'returned' | null
  return_ref: string | null
  returned_at: string | null
  returned_by: string | null
  replacement_status: 'expected' | 'received' | null
  replacement_expected_at: string | null
  replacement_received_at: string | null
  credit_note_number: string | null
}

export const useGoodsIssues = (caseId: string, enabled = true) =>
  useQuery({ queryKey: ['goods-issues', caseId], queryFn: () => api.get<GoodsIssue[]>(`/cases/${caseId}/goods-issues`), enabled })

function useRefresh(caseId: string) {
  const queryClient = useQueryClient()
  return () => {
    for (const key of ['goods-issues', 'invoices', 'cases', 'agent-flow', 'my-work', 'delivery']) {
      void queryClient.invalidateQueries({ queryKey: [key] })
    }
    void queryClient.invalidateQueries({ queryKey: ['goods-issues', caseId] })
  }
}

export function useReportIssue(caseId: string) {
  const refresh = useRefresh(caseId)
  return useMutation({
    mutationFn: (v: { kind: IssueKind; items?: Record<string, number>; description?: string }) =>
      api.post<GoodsIssue>(`/cases/${caseId}/goods-issues`, v),
    onSuccess: refresh,
  })
}

export function useResolveIssue(caseId: string) {
  const refresh = useRefresh(caseId)
  return useMutation({
    mutationFn: (v: { issueId: string; resolution: 'replaced' | 'credit' | 'accepted'; credit_amount?: number; credit_note_number?: string; note?: string }) =>
      api.post<GoodsIssue>(`/cases/${caseId}/goods-issues/${v.issueId}/resolve`, { resolution: v.resolution, credit_amount: v.credit_amount, credit_note_number: v.credit_note_number, note: v.note }),
    onSuccess: refresh,
  })
}

export function useReturnGoods(caseId: string) {
  const refresh = useRefresh(caseId)
  return useMutation({
    mutationFn: (v: { issueId: string; ref?: string }) => api.post<GoodsIssue>(`/cases/${caseId}/goods-issues/${v.issueId}/return`, { ref: v.ref }),
    onSuccess: refresh,
  })
}

export function useExpectReplacement(caseId: string) {
  const refresh = useRefresh(caseId)
  return useMutation({
    mutationFn: (issueId: string) => api.post<GoodsIssue>(`/cases/${caseId}/goods-issues/${issueId}/replacement-expected`),
    onSuccess: refresh,
  })
}

export function useReceiveReplacement(caseId: string) {
  const refresh = useRefresh(caseId)
  return useMutation({
    mutationFn: (v: { issueId: string; note?: string }) => api.post<GoodsIssue>(`/cases/${caseId}/goods-issues/${v.issueId}/replacement-received`, { note: v.note }),
    onSuccess: refresh,
  })
}
