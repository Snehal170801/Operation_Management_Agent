// Unless VITE_API_BASE_URL says otherwise, the API is on port 8000 of whatever host served this page,
// so localhost and the LAN address both work (and the refresh cookie stays same-site).
export const BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || `${window.location.protocol}//${window.location.hostname}:8000`
).replace(/\/$/, '')

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** Turns a non-2xx response into an ApiError carrying the backend's `detail` message. */
export async function toApiError(response: Response): Promise<ApiError> {
  let message = FRIENDLY[response.status] ?? (response.status >= 500 ? FRIENDLY[500] : response.statusText || 'Request failed')
  let ref: string | undefined
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') message = body.detail
    // a form the server rejected: {detail: [{loc, msg}, ...]} -> the first problem, in words
    else if (Array.isArray(body.detail) && body.detail[0]?.msg) message = `${String(body.detail[0].msg).replace(/^Value error, /, '')}`
    if (typeof body.request_id === 'string') ref = body.request_id
  } catch {
    /* non-JSON error body */
  }
  ref ??= response.headers.get('x-request-id') ?? undefined
  // For a server fault, quote the reference so support can find it in the log.
  return new ApiError(response.status, response.status >= 500 && ref ? `${message} (ref ${ref})` : message)
}

/** What to say when the server gave no message of its own. */
const FRIENDLY: Record<number, string> = {
  500: 'Something went wrong on our side. Please try again.',
  502: 'The server is restarting or unreachable. Please try again in a moment.',
  503: 'The service is busy or unavailable right now. Please try again in a moment.',
  504: 'The server took too long to answer. Please try again.',
}
