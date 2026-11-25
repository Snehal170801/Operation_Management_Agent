import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api-client'

export interface AppNotification {
  id: string
  /** approval | case | invoice (staff, need action) | my_request (requester, informational) */
  kind: string
  title: string
  message: string
  /** An in-app path to open. */
  link: string
  created_at: string
  requires_action: boolean
}

const POLL_MS = 30_000

/** The bell's content. Re-checked every 30s and whenever the tab regains focus. */
export const useNotifications = (enabled: boolean) =>
  useQuery({
    queryKey: ['notifications'],
    queryFn: () => api.get<AppNotification[]>('/notifications'),
    enabled,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  })

// "Seen" is remembered per user in this browser only: it just decides which informational
// (requester) items still count as new. Items that need action keep counting until resolved.
const seenKey = (userId: string) => `oa:notifications-seen:${userId}`

export function readSeenAt(userId: string): number {
  try {
    return Number(localStorage.getItem(seenKey(userId))) || 0
  } catch {
    return 0
  }
}

export function writeSeenAt(userId: string, at: number): void {
  try {
    localStorage.setItem(seenKey(userId), String(at))
  } catch {
    /* storage unavailable (private window): the badge just won't clear between visits */
  }
}

/** The backend sends UTC without a zone marker. */
export function toTime(value: string): number {
  const iso = /Z$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`
  return new Date(iso).getTime()
}
