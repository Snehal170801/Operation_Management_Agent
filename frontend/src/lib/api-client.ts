import { BASE_URL, toApiError } from './http'
import { refreshSession, tokenStore } from './session'

import { ApiError } from './http'

export { ApiError } from './http'

const REQUEST_TIMEOUT_MS = 30_000

async function request<T>(path: string, init?: RequestInit, canRetry = true, as: 'json' | 'blob' = 'json'): Promise<T> {
  const token = tokenStore.get()
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      credentials: 'include',
      // Never wait forever: a stalled server should give the person an answer, not a spinner.
      signal: init?.signal ?? AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init?.headers,
      },
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error // cancelled on purpose (leaving a page)
    if (error instanceof DOMException && error.name === 'TimeoutError') {
      throw new ApiError(0, 'The server took too long to answer. Please try again.')
    }
    // fetch only throws like this when the request never got an answer: offline, server down, blocked.
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.")
  }

  if (response.status === 401 && canRetry) {
    // Access token expired or was revoked: try once to get a fresh one, then replay the call.
    if (await refreshSession()) return request<T>(path, init, false, as)
    tokenStore.notifyExpired()
  }

  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return undefined as T
  if (as === 'blob') return response.blob() as Promise<T>
  return response.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  /** A file (such as a PDF): fetched with the sign-in so a plain link is not needed. */
  blob: (path: string) => request<Blob>(path, undefined, true, 'blob'),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) => request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
