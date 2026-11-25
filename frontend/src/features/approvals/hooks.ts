import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { approvalsApi } from './api'

export const approvalKeys = {
  all: ['approvals'] as const,
  list: (status?: string, caseId?: string) => ['approvals', status ?? 'all', caseId ?? 'any'] as const,
}

/** The full review of one decision. Under 'approvals', so the live connection refreshes it as quotes arrive. */
export const useApprovalReview = (approvalId: string, enabled = true) =>
  useQuery({ queryKey: ['approvals', 'review', approvalId], queryFn: () => approvalsApi.review(approvalId), refetchOnWindowFocus: true, enabled })

export const useApprovals = (status?: string, caseId?: string, enabled = true) =>
  useQuery({
    queryKey: approvalKeys.list(status, caseId),
    queryFn: () => approvalsApi.list(status, caseId),
    enabled,
  })

/** Approving or rejecting changes the case (stage, purchase order), so refresh those too. */
export function useDecideApproval() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ approvalId, approve, note, vendorId, reSource, skipSelected }: {
      approvalId: string
      approve: boolean
      note?: string
      vendorId?: string
      reSource?: boolean
      skipSelected?: boolean
    }) => (approve ? approvalsApi.approve(approvalId, note, vendorId) : approvalsApi.reject(approvalId, note, reSource, skipSelected)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: approvalKeys.all })
      void queryClient.invalidateQueries({ queryKey: ['cases'] })
      void queryClient.invalidateQueries({ queryKey: ['purchase-order'] })
      void queryClient.invalidateQueries({ queryKey: ['agent-flow'] })
      void queryClient.invalidateQueries({ queryKey: ['my-work'] })
    },
  })
}
