import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { purchaseOrdersApi } from './api'

export const usePurchaseOrders = () => useQuery({ queryKey: ['purchase-orders'], queryFn: purchaseOrdersApi.list })

export const usePurchaseOrder = (caseId: string, enabled = true) =>
  useQuery({
    queryKey: ['purchase-order', caseId],
    queryFn: () => purchaseOrdersApi.get(caseId),
    enabled,
  })

export function useConfirmPurchaseOrder(caseId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (note?: string) => purchaseOrdersApi.confirm(caseId, note),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['purchase-order', caseId] })
      void queryClient.invalidateQueries({ queryKey: ['my-work'] })
      void queryClient.invalidateQueries({ queryKey: ['agent-flow'] })
    },
  })
}

export function useIssuePurchaseOrder(caseId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => purchaseOrdersApi.issue(caseId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['purchase-order', caseId] })
      void queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
  })
}
