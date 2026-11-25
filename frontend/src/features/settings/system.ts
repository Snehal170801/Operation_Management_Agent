import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api-client'

export type CheckStatus = 'ok' | 'warning' | 'down'

export interface HealthCheck {
  name: string
  status: CheckStatus
  detail: string
  latency_ms: number | null
}

export interface SystemHealth {
  status: CheckStatus
  checked_at: string
  checks: HealthCheck[]
  info: {
    environment: string
    python_version: string
    started_at: string
    uptime_seconds: number
    database: string
    server_version: string | null
  }
  stats: {
    users: number
    active_sessions: number
    cases: number
    open_cases: number
    migrations_applied: number
  } | null
}

export const useSystemHealth = (enabled: boolean) =>
  useQuery({
    queryKey: ['system', 'health'],
    queryFn: () => api.get<SystemHealth>('/system/health'),
    enabled,
    refetchInterval: 10_000,
    staleTime: 0,
  })
