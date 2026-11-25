import type { Page } from '@playwright/test'

/** Collects everything that should never happen while a page is used: console errors, uncaught exceptions, failed or 4xx/5xx requests. */
export function watchProblems(page: Page, allow: RegExp[] = []) {
  const problems: string[] = []
  const ok = (text: string) => allow.some((re) => re.test(text))
  const add = (text: string) => { if (!ok(text)) problems.push(text) }
  page.on('console', (m) => { if (m.type() === 'error') add(`console error: ${m.text()}`) })
  page.on('pageerror', (e) => add(`uncaught: ${e.message}`))
  page.on('requestfailed', (r) => add(`request failed: ${r.method()} ${r.url()} (${r.failure()?.errorText})`))
  page.on('response', (r) => { if (r.status() >= 400) add(`HTTP ${r.status()}: ${r.request().method()} ${r.url()}`) })
  return problems
}

/** Things the app does on purpose that a browser logs as errors. Anything NOT on this list fails a test.
 *  - 401 on /auth/refresh: asking for a session before signing in
 *  - 404 on a case's purchase-order / delivery: "no order yet" is answered with 404 and the page shows an empty state
 *  - cut-off live stream and presence calls when the page is left */
export const EXPECTED_NOISE: RegExp[] = [
  /HTTP 401: POST .*\/auth\/refresh/,
  /HTTP 404: GET .*\/cases\/[0-9a-f-]{36}\/(purchase-order|delivery)$/i,
  /live\/stream.*ERR_ABORTED/,
  /presence\/cases\/.*ERR_ABORTED/,
  /console error: Failed to load resource: the server responded with a status of (401|404)/,
]
