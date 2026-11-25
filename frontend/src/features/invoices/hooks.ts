import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { invoicesApi } from './api'

export const useInvoices = (status?: string, enabled = true) =>
  useQuery({ queryKey: ['invoices', status ?? 'all'], queryFn: () => invoicesApi.list(status), enabled })

export const useCaseInvoices = (caseId: string, enabled = true) =>
  useQuery({ queryKey: ['invoices', 'case', caseId], queryFn: () => invoicesApi.forCase(caseId), enabled })

/** Invoices change the case (it can close), so refresh cases and the dashboard queue too. */
function useRefreshAfterInvoiceChange() {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: ['invoices'] })
    void queryClient.invalidateQueries({ queryKey: ['cases'] })
  }
}

export function useSubmitInvoice(caseId: string) {
  const refresh = useRefreshAfterInvoiceChange()
  return useMutation({ mutationFn: (rawText: string) => invoicesApi.submit(caseId, rawText), onSuccess: refresh })
}

export function useDecideInvoice() {
  const refresh = useRefreshAfterInvoiceChange()
  return useMutation({
    mutationFn: ({ invoiceId, approve, note }: { invoiceId: string; approve: boolean; note?: string }) =>
      approve ? invoicesApi.approve(invoiceId, note) : invoicesApi.reject(invoiceId, note),
    onSuccess: refresh,
  })
}
