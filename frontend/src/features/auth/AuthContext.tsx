import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api-client'
import { impersonation, loginRequest, logoutRequest, refreshSession, tokenStore } from '@/lib/session'
import type { AuthResponse, AuthUser } from './types'

type Status = 'loading' | 'authenticated' | 'anonymous'

interface AuthContextValue {
  status: Status
  user: AuthUser | null
  /** Set when an administrator opened this account from the Accounts tab: who opened it. */
  openedBy: string | null
  login: (username: string, password: string, rememberMe: boolean) => Promise<void>
  logout: () => Promise<void>
  /** Whether the signed-in user's role grants this permission (UI gating only; the API enforces it). */
  can: (permission: string) => boolean
  updateProfile: (displayName: string) => Promise<void>
  /** Changes the password; the server ends all other sessions and starts a fresh one here. */
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

// Refresh this long before the access token expires.
const REFRESH_LEEWAY_MS = 60_000
const CHANNEL = 'operation-agents-auth'

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<Status>('loading')
  const [user, setUser] = useState<AuthUser | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const channel = useRef<BroadcastChannel | null>(null)
  // The renewal timer calls the latest applySession through this ref (it can't capture itself).
  const applyRef = useRef<(session: AuthResponse) => void>(() => {})

  const clearLocal = useCallback(() => {
    clearTimeout(timer.current)
    tokenStore.clear()
    setUser(null)
    setStatus('anonymous')
    // Never leave one user's cached data around for the next person on this browser.
    queryClient.clear()
  }, [queryClient])

  const applySession = useCallback(
    (session: AuthResponse) => {
      setUser(session.user)
      setStatus('authenticated')
      clearTimeout(timer.current)
      // Silently renew just before expiry so users aren't interrupted mid-task.
      timer.current = setTimeout(async () => {
        const next = await refreshSession()
        if (next) applyRef.current(next)
        else clearLocal()
      }, Math.max(5_000, tokenStore.msLeft() - REFRESH_LEEWAY_MS))
    },
    [clearLocal],
  )

  useEffect(() => {
    applyRef.current = applySession
  }, [applySession])

  // Restore the session on load (and after a reload) from the refresh cookie. A tab an administrator opened for
  // another account instead collects that account's sign-in from the tab that opened it (once, from memory).
  useEffect(() => {
    let cancelled = false
    if (impersonation.get()) return // already collected (React runs this effect twice in development)
    const handoffId = new URLSearchParams(window.location.search).get('impersonate')
    if (handoffId) {
      let opened
      try {
        opened = window.opener?.__oaHandoff?.(handoffId)
      } catch {
        opened = undefined
      }
      window.history.replaceState(null, '', window.location.pathname) // the id is spent: take it out of the address
      if (opened) {
        tokenStore.set(opened.access_token, opened.expires_in)
        impersonation.start(opened.opened_by)
        void Promise.resolve(opened).then(applySession)
      } else {
        // reloaded, or opened from nowhere: there is nothing to sign in with; close the tab and open it again
        void Promise.resolve().then(clearLocal)
      }
      return
    }
    refreshSession().then((session) => {
      if (cancelled) return
      if (session) applySession(session)
      else clearLocal()
    })
    return () => {
      cancelled = true
    }
  }, [applySession, clearLocal])

  // A request anywhere failed to refresh -> drop to the login screen.
  useEffect(() => tokenStore.onExpired(clearLocal), [clearLocal])

  // Logging out in one tab logs out every tab.
  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return
    const bc = new BroadcastChannel(CHANNEL)
    channel.current = bc
    bc.onmessage = (event) => event.data === 'logout' && clearLocal()
    return () => {
      bc.close()
      channel.current = null
    }
  }, [clearLocal])

  // Background tabs throttle timers; re-check the token when the tab comes back.
  useEffect(() => {
    const onVisible = async () => {
      if (document.visibilityState !== 'visible' || status !== 'authenticated') return
      if (tokenStore.msLeft() > REFRESH_LEEWAY_MS) return
      const next = await refreshSession()
      if (next) applySession(next)
      else clearLocal()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [status, applySession, clearLocal])

  const login = useCallback(
    async (username: string, password: string, rememberMe: boolean) => {
      const session = await loginRequest(username, password, rememberMe)
      impersonation.stop() // a real sign-in in this tab replaces the opened account
      queryClient.clear()
      applySession(session)
    },
    [applySession, queryClient],
  )

  const logout = useCallback(async () => {
    if (impersonation.active()) {
      // An opened account has nothing to sign out of: just close this tab. The administrator's own session is untouched.
      clearLocal()
      window.close()
      return
    }
    await logoutRequest()
    clearLocal()
    channel.current?.postMessage('logout')
  }, [clearLocal])

  // An opened account's sign-in came from an administrator's tab (see the bootstrap above); it ends with the session.
  const openedBy = user ? impersonation.get() : null

  const can = useCallback((permission: string) => !!user?.permissions.includes(permission), [user])

  const updateProfile = useCallback(async (displayName: string) => {
    const updated = await api.patch<AuthUser>('/auth/me', { display_name: displayName })
    setUser(updated)
  }, [])

  const changePassword = useCallback(
    async (currentPassword: string, newPassword: string) => {
      const session = await api.post<AuthResponse>('/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      })
      tokenStore.set(session.access_token, session.expires_in)
      applySession(session)
    },
    [applySession],
  )

  const value = useMemo(
    () => ({ status, user, openedBy, login, logout, can, updateProfile, changePassword }),
    [status, user, openedBy, login, logout, can, updateProfile, changePassword],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
