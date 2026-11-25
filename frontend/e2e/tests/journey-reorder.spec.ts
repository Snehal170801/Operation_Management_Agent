import { expect, test, type Page } from '@playwright/test'
import { decideFromEmail, receiveGoods, suppliersQuote } from '../support/flows'
import { clearMail, readOutbox, waitForMail } from '../support/mail'
import { caseIdFromUrl, login, settle } from '../support/session'

test.beforeEach(() => clearMail())

const row = (page: Page, item: string) => page.getByRole('row').filter({ hasText: item })

test('low stock: Stores sets levels -> Order now -> an approver must approve -> goods in two parts -> stock reaches the target', async ({ page, browser }) => {
  test.setTimeout(240_000)
  const item = `A0 reorder widgets ${Date.now().toString(36)}` // sorts first, so it is on page 1 of the Stock table

  // Stores records an item with 5 in stock and sets levels: low at 10 or less, refill to 30
  await login(page, 'stores')
  await page.goto('/stock')
  await settle(page)
  await page.getByRole('button', { name: 'Add / update item' }).click()
  await page.getByLabel('Item description').fill(item)
  await page.getByLabel('Quantity available').fill('5')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await page.getByRole('button', { name: 'Add item', exact: true }).click()
  await expect(row(page, item)).toBeVisible()

  await page.getByRole('button', { name: `Set levels for ${item}` }).click()
  await page.getByLabel('Minimum level').fill('10')
  await page.getByLabel('Target level').fill('30')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(row(page, item)).toContainText('min 10 · target 30')
  await expect(row(page, item)).toContainText('Low')

  // Order now suggests enough to reach the target (25) and sends the request into the normal flow
  await row(page, item).getByRole('button', { name: 'Order now' }).click()
  await expect(page.getByLabel('How many to order')).toHaveValue('25')
  await page.getByRole('button', { name: 'Place order' }).click()
  await page.waitForURL(/\/cases\/[0-9a-f-]{36}/i) // the app opens the new case
  const caseId = caseIdFromUrl(page.url())!.toLowerCase()
  await expect(page.locator('main')).toContainText(`Restock 25 x ${item}`)
  await page.goto('/stock')
  await expect(row(page, item).getByRole('link', { name: /Ordered/ })).toBeVisible()
  await expect(row(page, item).getByRole('button', { name: 'Order now' })).toHaveCount(0) // no second order for the same item

  // suppliers are asked and quote a small amount: a reorder still needs an approver
  const rfqs = await waitForMail({ subject: `[OA-${caseId}] Request for quotation` }, 3)
  expect(rfqs[0].body).toContain(item)
  suppliersQuote(rfqs, { acme: 20_000, globex: 22_000, initech: 25_000 })
  const approvals = await waitForMail({ subject: /Approval needed/ }, 1)
  expect(approvals[0].body).toMatch(/reorder|low stock|restock/i)
  expect(readOutbox({ subject: /Purchase Order/ })).toHaveLength(0)

  await decideFromEmail(browser, approvals[0], 'approve')
  await waitForMail({ subject: /Purchase Order PO-/ })

  // goods arrive in two parts: stock rises each time, the "Ordered" tag stays until everything is in
  await page.context().clearCookies()
  await login(page, 'receiving')
  await receiveGoods(page, caseId, { [item]: 10 })
  await expect(page.locator('main')).toContainText(/Arrived so far\s*10 of 25/)

  await page.context().clearCookies()
  await login(page, 'stores')
  await page.goto('/stock')
  await expect(row(page, item).locator('td').nth(2)).toHaveText(/15$/)
  await expect(row(page, item).getByRole('link', { name: /Ordered/ })).toBeVisible()

  await page.context().clearCookies()
  await login(page, 'receiving')
  await receiveGoods(page, caseId, { [item]: 15 })
  await expect(page.locator('main')).toContainText(/Status\s*Delivered/)

  await page.context().clearCookies()
  await login(page, 'stores')
  await page.goto('/stock')
  await expect(row(page, item).locator('td').nth(2)).toHaveText(/30$/)
  await expect(row(page, item).getByRole('link', { name: /Ordered/ })).toHaveCount(0)
  await expect(row(page, item)).toContainText('OK')
})
