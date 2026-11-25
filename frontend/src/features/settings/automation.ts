import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api-client'

export interface AutomationState {
  paused: boolean
  updated_at: string | null
  updated_by: string | null
}

const KEY = ['system', 'automation'] as const

export const useAutomation = (enabled = true) =>
  useQuery({
    queryKey: KEY,
    queryFn: () => api.get<AutomationState>('/system/automation'),
    enabled,
    refetchInterval: 30_000,
  })

export function useSetAutomation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (paused: boolean) => api.post<AutomationState>('/system/automation', { paused }),
    onSuccess: (state) => queryClient.setQueryData(KEY, state),
  })
}
