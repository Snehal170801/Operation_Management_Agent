import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { pollMs, useLiveConnected } from '@/features/live/liveStore'
import { api } from '@/lib/api-client'
import type { DashboardSnapshot } from './types'

/** How often the live dashboard asks for fresh numbers while it is on screen. */
export const DASHBOARD_POLL_MS = 5_000

/** Live: re-fetched every few seconds (and straight away when the tab regains focus). Polling pauses
 *  while the tab is hidden, and the last numbers stay on screen if a refresh fails. */
export const useDashboard = (enabled = true) => {
  const live = useLiveConnected()
  return useQuery({
    queryKey: ['dashboard'],
    queryFn: () => api.get<DashboardSnapshot>('/dashboard'),
    enabled,
    refetchInterval: pollMs(live, DASHBOARD_POLL_MS),
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    staleTime: 0,
    placeholderData: keepPreviousData,
  })
}
