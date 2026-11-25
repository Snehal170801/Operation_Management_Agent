import { useQuery } from '@tanstack/react-query'
import { purchaseRequestsApi } from './api'

export const usePurchaseRequest = (caseId: string) =>
  useQuery({
    queryKey: ['purchase-requests', caseId],
    queryFn: () => purchaseRequestsApi.getByCase(caseId),
  })
