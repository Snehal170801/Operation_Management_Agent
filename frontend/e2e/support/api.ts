import { request, type APIRequestContext } from '@playwright/test'
import { API, PASSWORD } from './accounts'

/** A signed-in API client for one account (Bearer token), for checking what the SERVER allows, whatever the screens show. */
export async function apiAs(username: string): Promise<APIRequestContext & { token: string }> {
  const anon = await request.newContext({ baseURL: API })
  const res = await anon.post('/auth/login', { data: { username, password: PASSWORD } })
  if (!res.ok()) throw new Error(`API login failed for ${username}: ${res.status()}`)
  const { access_token } = await res.json()
  await anon.dispose()
  const ctx = await request.newContext({ baseURL: API, extraHTTPHeaders: { Authorization: `Bearer ${access_token}` } })
  return Object.assign(ctx, { token: access_token as string })
}

/** Files a request over the API as `username`; returns the case id. */
export async function createCaseAs(username: string, rawRequest: string): Promise<string> {
  const api = await apiAs(username)
  const res = await api.post('/cases', { data: { raw_request: rawRequest } })
  if (!res.ok()) throw new Error(`creating a case as ${username} failed: ${res.status()} ${await res.text()}`)
  const body = await res.json()
  await api.dispose()
  return String(body.case_id).toLowerCase()
}
