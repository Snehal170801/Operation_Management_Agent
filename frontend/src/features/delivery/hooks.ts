import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { deliveryApi } from './api'

export const useDelivery = (caseId: string, enabled = true) =>
  useQuery({ queryKey: ['delivery', caseId], queryFn: () => deliveryApi.get(caseId), enabled })

export function useConfirmDelivery(caseId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ note, items }: { note?: string; items?: Record<string, number> }) => deliveryApi.confirmReceived(caseId, note, items),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['delivery', caseId] })
      void queryClient.invalidateQueries({ queryKey: ['cases'] })
      // Confirming receipt also releases a held invoice and can close the case, so refresh those too.
      void queryClient.invalidateQueries({ queryKey: ['invoices'] })
      void queryClient.invalidateQueries({ queryKey: ['agent-flow'] })
    },
  })
}

export function useShortClose(caseId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (note?: string) => deliveryApi.shortClose(caseId, note),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['delivery', caseId] })
      void queryClient.invalidateQueries({ queryKey: ['cases'] })
      void queryClient.invalidateQueries({ queryKey: ['invoices'] })
      void queryClient.invalidateQueries({ queryKey: ['agent-flow'] })
      void queryClient.invalidateQueries({ queryKey: ['my-work'] })
    },
  })
}
