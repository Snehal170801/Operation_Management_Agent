import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { pollMs, useLiveConnected } from '@/features/live/liveStore'
import { casesApi } from './api'

export const caseKeys = {
  all: ['cases'] as const,
  detail: (id: string) => ['cases', id] as const,
  events: (id: string) => ['cases', id, 'events'] as const,
}

export const useCases = (enabled = true) =>
  useQuery({ queryKey: caseKeys.all, queryFn: casesApi.list, enabled })

/** `refetchMs` turns on live polling (pass false/undefined for none). */
export const useCase = (id: string, refetchMs?: number | false) => {
  const live = useLiveConnected()
  return useQuery({ queryKey: caseKeys.detail(id), queryFn: () => casesApi.get(id), refetchInterval: refetchMs ? pollMs(live, refetchMs) : false })
}

export const useCaseEvents = (id: string, refetchMs?: number | false) => {
  const live = useLiveConnected()
  return useQuery({ queryKey: caseKeys.events(id), queryFn: () => casesApi.events(id), refetchInterval: refetchMs ? pollMs(live, refetchMs) : false })
}

export function useCreateCase() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: casesApi.create,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: caseKeys.all }),
  })
}
