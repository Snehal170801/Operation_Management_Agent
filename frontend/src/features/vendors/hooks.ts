import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { vendorsApi } from './api'

const KEY = ['vendors'] as const

export const useVendors = () => useQuery({ queryKey: KEY, queryFn: vendorsApi.list })

export function useUpsertVendor() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: vendorsApi.upsert,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  })
}

export function useUpdateVendor() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Parameters<typeof vendorsApi.update>[1] }) => vendorsApi.update(id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['stock'] }) // the preferred supplier's name is shown on the stock list
      return queryClient.invalidateQueries({ queryKey: KEY })
    },
  })
}

export const useQuotes = (caseId: string, enabled = true) =>
  useQuery({ queryKey: ['cases', caseId, 'quotes'], queryFn: () => vendorsApi.quotes(caseId), enabled })

/** Enter a supplier's quote by hand (e.g. they phoned it in). The agent reads the text like an emailed one. */
export function useSubmitQuote(caseId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { vendor_id: string; raw_quote_text: string }) => vendorsApi.submitQuote(caseId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['cases', caseId] })
    },
  })
}

export const useRfqs = (caseId: string, enabled = true) =>
  useQuery({ queryKey: ['cases', caseId, 'rfqs'], queryFn: () => vendorsApi.rfqs(caseId), enabled })
