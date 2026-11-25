import { useCallback, useState } from 'react'
import { api } from '@/lib/api-client'
import type { OpenedAccount } from '@/features/auth/types'

declare global {
  interface Window {
    /** The new tab collects its sign-in from the tab that opened it: once, and never through storage or the address bar. */
    __oaHandoff?: (id: string) => OpenedAccount | undefined
  }
}

const pending = new Map<string, OpenedAccount>()
const HANDOFF_LIFETIME_MS = 60_000

if (typeof window !== 'undefined') {
  window.__oaHandoff = (id) => {
    const session = pending.get(id)
    pending.delete(id) // handed over once, then gone
    return session
  }
}

/** A random one-off id. `crypto.randomUUID` only exists on https:// or localhost, and this app is opened on a plain
 *  http:// network address, so use `getRandomValues`, which works everywhere. */
function newHandoffId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

/** Opens a department's account in a NEW tab, without its password (administrators only). The sign-in is passed
 *  straight from this tab to the new one in memory; it is never put in the address or in browser storage. */
export function useOpenAccount() {
  const [busy, setBusy] = useState<string>()
  const [error, setError] = useState<string>()

  const open = useCallback(async (userId: string) => {
    setError(undefined)
    setBusy(userId)
    // Open the tab right now, inside the click, or the browser's pop-up blocker would stop it after the wait.
    const tab = window.open('', '_blank')
    try {
      const session = await api.post<OpenedAccount>(`/users/${userId}/open-session`)
      const id = newHandoffId()
      pending.set(id, session)
      setTimeout(() => pending.delete(id), HANDOFF_LIFETIME_MS)
      const url = `/?impersonate=${id}`
      if (tab) tab.location.href = url
      else window.open(url, '_blank')
    } catch (e) {
      tab?.close()
      setError(e instanceof Error ? e.message : 'Could not open that account.')
    } finally {
      setBusy(undefined)
    }
  }, [])

  return { open, busy, error }
}
