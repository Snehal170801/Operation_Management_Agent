import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api-client'

export interface ConfigItem {
  key: string
  label: string
  help: string
  kind: 'int' | 'float' | 'bool'
  unit: string
  minimum: number
  maximum: number
  value: number | boolean
  default: number | boolean
  changed: boolean
}

export interface ConfigGroup {
  key: string
  label: string
  help: string
  items: ConfigItem[]
}

const KEY = ['config'] as const

export const useConfig = () => useQuery({ queryKey: KEY, queryFn: () => api.get<{ groups: ConfigGroup[] }>('/config') })

export function useSaveConfig() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (values: Record<string, number | boolean | string>) => api.put<{ groups: ConfigGroup[] }>('/config', { values }),
    onSuccess: (data) => queryClient.setQueryData(KEY, data),
  })
}

export function useResetConfig() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (keys: string[] | null) => api.post<{ groups: ConfigGroup[] }>('/config/reset', { keys }),
    onSuccess: (data) => queryClient.setQueryData(KEY, data),
  })
}
