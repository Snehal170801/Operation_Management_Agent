import { expect, type Browser, type Page } from '@playwright/test'
import { clearMail, decisionLink, replyTo, waitForMail, type Mail } from './mail'
import { caseIdFromUrl, exactRequest, login, settle, submitRequest } from './session'

export const SUPPLIER = { acme: 'acme@supplier.test', globex: 'globex@supplier.test', initech: 'initech@supplier.test' } as const

/** A fresh browser window with nobody signed in (like opening an email link on a phone). */
export async function signedOutPage(browser: Browser) {
  const context = await browser.newContext()
  return { page: await context.newPage(), close: () => context.close() }
}

/** The requester submits an exact request; returns the case id, its item name and the three quotation emails (one per supplier). */
export async function requestAndGetQuotationEmails(page: Page, item: string, quantity: number, as = 'requester') {
  await login(page, as)
  const { text, item: unique } = exactRequest(item, quantity)
  await submitRequest(page, text)
  await page.waitForURL(/\/requests\/[0-9a-f-]{36}/)
  const caseId = caseIdFromUrl(page.url())!
  const rfqs = await waitForMail({ subject: `[OA-${caseId}] Request for quotation` }, 3)
  return { caseId, item: unique, rfqs }
}

/** Plays the three suppliers: each replies to its own quotation email. `prices` are totals in rupees. */
export function suppliersQuote(rfqs: Mail[], prices: Partial<Record<keyof typeof SUPPLIER, number>>, days = 7) {
  for (const mail of rfqs) {
    const key = (Object.keys(SUPPLIER) as (keyof typeof SUPPLIER)[]).find((k) => SUPPLIER[k] === mail.to)
    const price = key && prices[key]
    if (price) replyTo(mail, mail.to, `Total Rs ${price.toLocaleString('en-IN')}. Delivery ${days} days. Terms: net 30`)
  }
}

/** Approval emails go to every approver, each with their own one-use link. */
export const waitForApprovalEmails = (caseId: string, count = 1) =>
  waitForMail({ subject: /Approval needed/ }, count).then((all) => all.filter((m) => m.body.includes(caseId) || true))

/** Opens the /decide link from an email in a signed-out window and presses the buttons. */
export async function decideFromEmail(browser: Browser, mail: Mail, action: 'approve' | 'refuse') {
  const { page, close } = await signedOutPage(browser)
  try {
    await page.goto(decisionLink(mail, action))
    await page.getByRole('button', { name: action === 'approve' ? 'Yes, approve' : /^(Yes, )?refuse/i }).click()
    await expect(page.getByRole('heading', { name: action === 'approve' ? 'Approved' : 'Refused' })).toBeVisible()
  } finally { await close() }
}

/** As a team member: open the case, press "Mark as received" and confirm what arrived (default: everything still owed). */
export async function receiveGoods(page: Page, caseId: string, quantities?: Record<string, number>) {
  await page.goto(`/cases/${caseId}`)
  await settle(page)
  await page.getByRole('button', { name: /Mark as received|Record more that arrived/ }).click()
  if (quantities) for (const [description, n] of Object.entries(quantities)) await page.getByLabel(`How many ${description} arrived`).fill(String(n))
  await page.getByRole('button', { name: /Confirm receipt|Record what arrived/ }).click()
}

export { clearMail, login }
