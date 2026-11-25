import type { AuthResponse } from '@/features/auth/types'
import { BASE_URL, toApiError } from './http'

/**
 * The access token lives only in memory — never localStorage — so XSS can't read it from
 * storage. The long-lived refresh token is an httpOnly cookie the page can't see at all;
 * a reload recovers the session by calling /auth/refresh.
 */
let accessToken: string | null = null
let expiresAt = 0
const expiredListeners = new Set<() => void>()

export const tokenStore = {
  get: () => accessToken,
  /** Milliseconds until the access token expires (0 if none). */
  msLeft: () => (accessToken ? Math.max(0, expiresAt - Date.now()) : 0),
  set(token: string, expiresInSeconds: number) {
    accessToken = token
    expiresAt = Date.now() + expiresInSeconds * 1000
  },
  clear() {
    accessToken = null
    expiresAt = 0
  },
  /** Subscribe to "the session is gone" (refresh failed). Returns an unsubscribe fn. */
  onExpired(listener: () => void) {
    expiredListeners.add(listener)
    return () => {
      expiredListeners.delete(listener)
    }
  },
  notifyExpired() {
    accessToken = null
    expiresAt = 0
    expiredListeners.forEach((fn) => fn())
  },
}

/** Set in a tab an administrator opened for another account. That tab has no sign-in of its own to renew, and the
 *  browser's refresh cookie is the ADMINISTRATOR's, so it must never be used there (it would turn the tab back into
 *  the administrator) and signing out must never end the administrator's own session. */
let openedBy: string | null = null
// A reload wipes memory but not this tab's own storage, so a flag (only a flag, never a sign-in) remembers that THIS
// tab was opened for another account. Without it, a reload would quietly turn the tab back into the administrator.
const FLAG = 'oa.opened-account'
const flagged = () => {
  try {
    return sessionStorage.getItem(FLAG) === '1'
  } catch {
    return false
  }
}
export const impersonation = {
  /** Who opened this account (in memory; gone after a reload). */
  get: () => openedBy,
  /** This tab belongs to an opened account, even after a reload: it must never use the refresh cookie. */
  active: () => openedBy !== null || flagged(),
  start(by: string) {
    openedBy = by
    try {
      sessionStorage.setItem(FLAG, '1')
    } catch {
      /* private window: the reload protection is lost, the rest still works */
    }
  },
  stop() {
    openedBy = null
    try {
      sessionStorage.removeItem(FLAG)
    } catch {
      /* nothing to remove */
    }
  },
}

async function authFetch(path: string, init: RequestInit): Promise<Response> {
  return fetch(`${BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...init.headers },
  })
}

export async function loginRequest(username: string, password: string, rememberMe: boolean): Promise<AuthResponse> {
  const response = await authFetch('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password, remember_me: rememberMe }),
  })
  if (!response.ok) throw await toApiError(response)
  const data: AuthResponse = await response.json()
  tokenStore.set(data.access_token, data.expires_in)
  return data
}

// Refresh tokens are single-use, so concurrent callers (StrictMode, several 401s at once)
// must share one in-flight request instead of racing each other.
let inFlight: Promise<AuthResponse | null> | null = null

/** Trades the refresh cookie for a new access token. Resolves null if there is no valid session. */
export function refreshSession(): Promise<AuthResponse | null> {
  if (impersonation.active()) return Promise.resolve(null)
  if (!inFlight) {
    inFlight = (async () => {
      try {
        const response = await authFetch('/auth/refresh', { method: 'POST' })
        if (!response.ok) return null
        const data: AuthResponse = await response.json()
        tokenStore.set(data.access_token, data.expires_in)
        return data
      } catch {
        return null
      } finally {
        inFlight = null
      }
    })()
  }
  return inFlight
}

export async function logoutRequest(): Promise<void> {
  if (impersonation.active()) return
  try {
    await authFetch('/auth/logout', { method: 'POST' })
  } catch {
    /* offline: the local session is cleared regardless */
  }
}
