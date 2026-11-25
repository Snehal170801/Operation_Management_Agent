import { expect, test } from '@playwright/test'
import { ADMIN } from '../support/accounts'
import { requestAndGetQuotationEmails, signedOutPage } from '../support/flows'
import { clearMail } from '../support/mail'
import { hasHorizontalScroll, login, settle } from '../support/session'
import { EXPECTED_NOISE, watchProblems } from '../support/watch'

test.beforeEach(() => clearMail())

const VIEWPORTS = [{ width: 1440, height: 900 }, { width: 390, height: 844 }]

test('case and request pages open cleanly for the right people at both widths', async ({ page, browser }) => {
  test.setTimeout(180_000)
  const { caseId } = await requestAndGetQuotationEmails(page, 'Pallet jacks', 2)

  const problems = watchProblems(page, EXPECTED_NOISE)
  for (const vp of VIEWPORTS) {
    await page.setViewportSize(vp)
    await page.goto(`/requests/${caseId}`) // the requester's own page
    await settle(page)
    await expect(page.getByText('Your request')).toBeVisible()
    expect(await hasHorizontalScroll(page), `request page at ${vp.width}`).toBe(false)
  }
  expect(problems).toEqual([])

  const staff = await browser.newContext()
  const sp = await staff.newPage()
  const staffProblems = watchProblems(sp, EXPECTED_NOISE)
  await login(sp, ADMIN)
  for (const vp of VIEWPORTS) {
    await sp.setViewportSize(vp)
    await sp.goto(`/cases/${caseId}`)
    await settle(sp)
    await expect(sp.getByText('Suppliers & quotes')).toBeVisible()
    expect(await hasHorizontalScroll(sp), `case page at ${vp.width}`).toBe(false)
  }
  expect(staffProblems).toEqual([])
  await staff.close()
})

test('a page that does not exist shows the not-found page, not a crash', async ({ page }) => {
  const problems = watchProblems(page, EXPECTED_NOISE)
  await login(page, ADMIN)
  await page.goto('/there-is-no-such-page')
  await settle(page)
  await expect(page.getByText(/not found/i).first()).toBeVisible()
  expect(problems).toEqual([])
})

test('an unknown case is "not found" for staff', async ({ page }) => {
  await login(page, ADMIN)
  await page.goto('/cases/00000000-0000-0000-0000-000000000000')
  await settle(page)
  await expect(page.getByText(/No case found with id 00000000/)).toBeVisible()
})

test('a made-up or garbled decision link is refused politely, signed out', async ({ browser }) => {
  const { page, close } = await signedOutPage(browser)
  const problems = watchProblems(page, [...EXPECTED_NOISE, /HTTP 4\d\d: GET .*\/decisions\//])
  for (const token of ['not-a-real-token', 'x'.repeat(200)]) {
    await page.goto(`/decide/${token}?a=approve`)
    await settle(page)
    await expect(page.getByRole('button', { name: 'Yes, approve' })).toHaveCount(0)
    await expect(page.locator('body')).toContainText(/link|not found|expired|no longer/i)
    expect(await hasHorizontalScroll(page)).toBe(false)
  }
  expect(problems).toEqual([])
  await close()
})
