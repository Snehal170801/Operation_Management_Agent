import { useQuery } from '@tanstack/react-query'
import { pollMs, useLiveConnected } from '@/features/live/liveStore'
import { api } from '@/lib/api-client'
import type { MyWork } from './types'

/** The signed-in person's own queue. Under its own key, so the live connection refreshes it the moment a case
 *  changes; the timer is only a safety net (stock levels, for one, change without an event). */
export const useMyWork = () => {
  const live = useLiveConnected()
  return useQuery({
    queryKey: ['my-work'],
    queryFn: () => api.get<MyWork>('/my-work'),
    refetchInterval: pollMs(live, 10_000),
    refetchOnWindowFocus: true,
  })
}
