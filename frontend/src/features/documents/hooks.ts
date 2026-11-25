import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { documentsApi } from './api'

const KEY = ['documents', 'unmatched'] as const

export const useUnmatchedDocuments = () => useQuery({ queryKey: KEY, queryFn: documentsApi.list, refetchInterval: 30_000 })

export function useAttachDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, caseId }: { id: string; caseId: string }) => documentsApi.attach(id, caseId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KEY })
      void queryClient.invalidateQueries({ queryKey: ['cases'] })
      void queryClient.invalidateQueries({ queryKey: ['my-work'] })
    },
  })
}

export function useDismissDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note?: string }) => documentsApi.dismiss(id, note),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  })
}
