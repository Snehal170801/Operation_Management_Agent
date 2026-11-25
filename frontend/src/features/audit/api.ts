import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { api } from '@/lib/api-client'

export interface AuditEntry {
  audit_id: number
  actor_user_id: string | null
  actor_username: string | null
  action: string
  outcome: 'success' | 'failure' | 'denied' | string
  target_type: string | null
  target_id: string | null
  detail: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
}

export interface AuditPage {
  total: number
  items: AuditEntry[]
}

export interface AuditFilters {
  limit: number
  offset: number
  action: string
  outcome: string
  search: string
  days: string
}

export function useAudit(filters: AuditFilters) {
  const params = new URLSearchParams({ limit: String(filters.limit), offset: String(filters.offset) })
  if (filters.action) params.set('action', filters.action)
  if (filters.outcome) params.set('outcome', filters.outcome)
  if (filters.search.trim()) params.set('search', filters.search.trim())
  if (filters.days) params.set('days', filters.days)

  return useQuery({
    queryKey: ['audit', params.toString()],
    queryFn: () => api.get<AuditPage>(`/audit?${params}`),
    placeholderData: keepPreviousData, // keep the old rows on screen while the next page loads
    staleTime: 5_000,
  })
}
