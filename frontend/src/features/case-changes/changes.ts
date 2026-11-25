import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api-client'

export interface ChangeLine {
  item: string
  from: number
  to: number
}

export interface ChangeOptions {
  /** before_order | after_order | cancelling | delivered | closed */
  phase: 'before_order' | 'after_order' | 'cancelling' | 'delivered' | 'from_stock' | 'closed'
  can_cancel: boolean
  can_change: boolean
  note: string
  items: { description: string; quantity: number }[]
  pending_change: { changes: ChangeLine[]; by: string | null; note: string | null; at: string } | null
}

export interface ChangeOutcome {
  outcome: string
  suppliers_told: string[]
}

export const useChangeOptions = (caseId: string) =>
  useQuery({ queryKey: ['change-options', caseId], queryFn: () => api.get<ChangeOptions>(`/cases/${caseId}/change-options`) })

/** Everything these actions touch: the request itself, its order, the agents' view and the queues. */
function useRefresh(caseId: string) {
  const queryClient = useQueryClient()
  return () => {
    for (const key of ['change-options', 'cases', 'purchase-order', 'purchase-request', 'agent-flow', 'my-work', 'approvals', 'delivery']) {
      void queryClient.invalidateQueries({ queryKey: [key] })
    }
    void queryClient.invalidateQueries({ queryKey: ['change-options', caseId] })
  }
}

export function useCancelCase(caseId: string) {
  const refresh = useRefresh(caseId)
  return useMutation({ mutationFn: (reason?: string) => api.post<ChangeOutcome>(`/cases/${caseId}/cancel`, { reason }), onSuccess: refresh })
}

export function useChangeCase(caseId: string) {
  const refresh = useRefresh(caseId)
  return useMutation({
    mutationFn: (v: { quantities: Record<string, number>; note?: string }) => api.post<ChangeOutcome>(`/cases/${caseId}/change`, v),
    onSuccess: refresh,
  })
}

export function useResolveCancel(caseId: string) {
  const refresh = useRefresh(caseId)
  return useMutation({
    mutationFn: (v: { action: 'settled' | 'carry_on'; note?: string }) => api.post<ChangeOutcome>(`/cases/${caseId}/cancel/resolve`, v),
    onSuccess: refresh,
  })
}

export function useResolveChange(caseId: string) {
  const refresh = useRefresh(caseId)
  return useMutation({
    mutationFn: (v: { action: 'amended' | 'declined'; total_amount?: number; note?: string }) =>
      api.post<ChangeOutcome>(`/cases/${caseId}/change/resolve`, v),
    onSuccess: refresh,
  })
}
