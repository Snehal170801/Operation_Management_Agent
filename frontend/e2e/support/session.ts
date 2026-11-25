import { expect, type Page } from '@playwright/test'
import { PASSWORD } from './accounts'

export async function login(page: Page, username: string, password = PASSWORD) {
  await page.goto('/login')
  await page.getByLabel('Email or username').fill(username)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: /sign in|log in/i }).click()
  await expect(page).not.toHaveURL(/\/login/)
}

/** True when the page scrolls sideways. */
export const hasHorizontalScroll = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)

/** The app polls the server, so the network is never idle. Wait for the page to load, then give its first requests a moment to answer. */
export async function settle(page: Page) {
  await page.waitForLoadState('load')
  await page.waitForTimeout(1000)
}

/** As a requester: type a request on My requests, confirm, and return the id of the new case (from the page it opens or the list). */
export async function submitRequest(page: Page, text: string) {
  await page.goto('/requests')
  await settle(page)
  await page.getByPlaceholder(/I need 10 laptops/).fill(text)
  await page.getByRole('button', { name: 'Submit request' }).click()
  await page.getByRole('button', { name: 'Send request', exact: true }).click()
}

/** The case id (a uuid) from a /cases/<id> or /requests/<id> address. */
export const caseIdFromUrl = (url: string) => url.match(/\/(?:cases|requests)\/([0-9a-f-]{36})/i)?.[1]

/** A request the AI stand-in reads exactly (TESTJSON), with an item name no earlier test used, so it is never mistaken for a duplicate or for stock. */
export function exactRequest(item: string, quantity: number) {
  const unique = `${item} ${Date.now().toString(36)}`
  return { text: `TESTJSON: ${JSON.stringify({ items: [{ description: unique, quantity }], cost_center: null })}`, item: unique }
}
