import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { BASE_URL } from '@/lib/http'
import { refreshSession, tokenStore } from '@/lib/session'
import { setLiveConnected } from './liveStore'

/** Screens that are not about cases and need no refresh when one changes. */
const NOT_AFFECTED = new Set(['users', 'audit'])
const THROTTLE_MS = 250
const MAX_RETRY_MS = 15_000

/** Opens the live connection for the whole signed-in app. Each "a case changed" signal makes whatever is on
 *  screen re-read itself, so a change shows up within a fraction of a second. If the connection drops it
 *  reconnects by itself (and the pages go back to polling until it is up again). */
export function useLiveUpdates(): void {
  const queryClient = useQueryClient()

  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let pending = false

    // Several signals in a burst (an agent writes a few events at once) cost one refresh, not many.
    const refresh = () => {
      if (timer) {
        pending = true
        return
      }
      void queryClient.invalidateQueries({ predicate: (q) => !NOT_AFFECTED.has(String(q.queryKey[0])) })
      timer = setTimeout(() => {
        timer = undefined
        if (pending) {
          pending = false
          refresh()
        }
      }, THROTTLE_MS)
    }

    async function listen(): Promise<void> {
      const response = await fetch(`${BASE_URL}/live/stream`, {
        headers: { Authorization: `Bearer ${tokenStore.get() ?? ''}`, Accept: 'text/event-stream' },
        credentials: 'include',
        signal: controller.signal,
      })
      if (response.status === 401) {
        if (!(await refreshSession())) tokenStore.notifyExpired()
        throw new Error('not signed in')
      }
      if (!response.ok || !response.body) throw new Error(`live stream ${response.status}`)

      setLiveConnected(true)
      refresh() // catch up on anything that changed while we were not connected
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) return
        buffer += decoder.decode(value, { stream: true })
        let end: number
        while ((end = buffer.indexOf('\n\n')) >= 0) {
          const block = buffer.slice(0, end)
          buffer = buffer.slice(end + 2)
          const data = block.split('\n').find((line) => line.startsWith('data:'))
          if (data && !data.includes('"hello"')) refresh()
        }
      }
    }

    void (async () => {
      let delay = 1_000
      while (!controller.signal.aborted) {
        try {
          await listen()
          delay = 1_000 // it ran fine and ended normally (the server renews connections every few minutes)
        } catch {
          if (controller.signal.aborted) return
        }
        setLiveConnected(false)
        await new Promise((resolve) => setTimeout(resolve, delay))
        delay = Math.min(delay * 2, MAX_RETRY_MS)
      }
    })()

    return () => {
      controller.abort()
      if (timer) clearTimeout(timer)
      setLiveConnected(false)
    }
  }, [queryClient])
}
