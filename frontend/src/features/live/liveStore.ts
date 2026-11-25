import { useSyncExternalStore } from 'react'

/** Whether the live connection to the server is up right now. */
let connected = false
const listeners = new Set<() => void>()

export function setLiveConnected(value: boolean): void {
  if (connected === value) return
  connected = value
  listeners.forEach((listener) => listener())
}

export function useLiveConnected(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => connected,
  )
}

/** How often a page re-reads on its own. While the live connection is up the server tells the page when
 *  something changed, so polling drops to a slow safety net; without it, the normal quick interval applies. */
export const pollMs = (live: boolean, fastMs: number, safetyNetMs = 30_000): number => (live ? Math.max(fastMs, safetyNetMs) : fastMs)
