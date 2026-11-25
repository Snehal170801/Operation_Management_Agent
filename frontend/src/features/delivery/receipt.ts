import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api-client'

export interface Receipt {
  /** not_delivered | ask | confirmed | disputed | followed_up */
  state: 'not_delivered' | 'ask' | 'confirmed' | 'disputed' | 'followed_up'
  note: string | null
  at: string | null
}

const refresh = (queryClient: ReturnType<typeof useQueryClient>, caseId: string) => {
  void queryClient.invalidateQueries({ queryKey: ['receipt', caseId] })
  void queryClient.invalidateQueries({ queryKey: ['my-work'] })
  void queryClient.invalidateQueries({ queryKey: ['agent-flow'] })
}

/** The requester's own answer, for their own request. */
export const useMyReceipt = (caseId: string) =>
  useQuery({ queryKey: ['receipt', caseId, 'mine'], queryFn: () => api.get<Receipt>(`/cases/${caseId}/receipt`) })

/** What the requester said, for the staff who follow up. */
export const useReceiptForStaff = (caseId: string, enabled: boolean) =>
  useQuery({ queryKey: ['receipt', caseId, 'staff'], queryFn: () => api.get<Receipt>(`/cases/${caseId}/delivery/receipt`), enabled })

export function useAnswerReceipt(caseId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (v: { received: boolean; note?: string }) => api.post<Receipt>(`/cases/${caseId}/receipt`, v),
    onSuccess: () => refresh(queryClient, caseId),
  })
}

export function useDisputeHandled(caseId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (note?: string) => api.post<void>(`/cases/${caseId}/delivery/dispute-handled`, { note }),
    onSuccess: () => refresh(queryClient, caseId),
  })
}
