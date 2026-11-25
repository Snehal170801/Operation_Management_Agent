import { expect, test } from '@playwright/test'
import { ADMIN, REQUESTER } from '../support/accounts'
import { decideFromEmail, receiveGoods, requestAndGetQuotationEmails, signedOutPage, suppliersQuote } from '../support/flows'
import { clearMail, readOutbox, replyTo, waitForMail } from '../support/mail'
import { login, settle } from '../support/session'

test.beforeEach(() => clearMail())

test('request -> suppliers quote -> approver approves from the email -> order -> goods -> invoice matched -> closed', async ({ page, browser }) => {
  test.setTimeout(240_000)

  // 1. the requester asks for something we do not stock
  const { caseId, item, rfqs } = await requestAndGetQuotationEmails(page, 'Steel storage racks', 8)
  await expect(page.getByText(/asked suppliers for prices/i).first()).toBeVisible()
  expect(rfqs.map((m) => m.to).sort()).toEqual(['acme@supplier.test', 'globex@supplier.test', 'initech@supplier.test'])
  expect(rfqs[0].body).toContain(item)

  // 2. the suppliers answer; the amount is over the auto-approve limit, so a person must decide
  suppliersQuote(rfqs, { acme: 90_000, globex: 95_000, initech: 99_000 })
  const approvals = await waitForMail({ subject: /Approval needed/ }, 2)
  expect(approvals.map((m) => m.to).sort()).toEqual(['admin@e2e.test', 'manager@e2e.test'])
  expect(approvals[0].body).toContain('Acme Supplies')
  expect(readOutbox({ subject: /Purchase Order/ })).toHaveLength(0) // nothing is ordered before approval

  // the requester sees the wait, but no prices or supplier names
  await page.reload()
  await settle(page)
  await expect(page.getByText("Waiting for a manager's approval.")).toBeVisible()
  await expect(page.locator('main')).not.toContainText('Acme Supplies')
  await expect(page.locator('main')).not.toContainText('90,000')

  // 3. the admin presses Approve in the email (no login)
  await decideFromEmail(browser, approvals.find((m) => m.to === 'admin@e2e.test')!, 'approve')

  // 4. the purchase order goes to the winning supplier only
  const [po] = await waitForMail({ subject: /Purchase Order PO-/ })
  expect(po.to).toBe('acme@supplier.test')
  const poNumber = po.subject.match(/PO-\d+/)![0]
  expect(readOutbox({ subject: /Purchase Order/ })).toHaveLength(1)

  // the manager's own link was for the same decision: it no longer works
  const late = await signedOutPage(browser)
  const { decisionLink } = await import('../support/mail')
  await late.page.goto(decisionLink(approvals.find((m) => m.to === 'manager@e2e.test')!, 'approve'))
  await expect(late.page.getByText(/no longer needed|already been decided|already been used/i)).toBeVisible()
  await expect(late.page.getByRole('button', { name: 'Yes, approve' })).toHaveCount(0)
  await late.close()

  // 5. receiving confirms the goods arrived
  await page.context().clearCookies()
  await login(page, 'receiving')
  await receiveGoods(page, caseId)
  await expect(page.locator('main')).toContainText(/Status\s*Delivered/)

  // 6. the supplier invoices by replying to the order email; accounts' check matches it to the order
  replyTo(po, 'acme@supplier.test', `Invoice INV-${Date.now() % 100000}. ${poNumber}. 8 x ${item}. Total Rs 90,000.`)
  await page.context().clearCookies()
  await login(page, ADMIN)
  await page.goto(`/cases/${caseId}`)
  await expect(page.locator('main')).toContainText('Matched', { timeout: 60_000 })
  await expect(page.locator('main')).toContainText('Approved', { timeout: 60_000 })
  await expect(page.locator('main')).toContainText(/Stage\s*Completed\s*Status\s*Closed/, { timeout: 60_000 })

  // 7. the requester sees it finished
  await page.context().clearCookies()
  await login(page, REQUESTER)
  await page.goto(`/requests/${caseId}`)
  await expect(page.getByText('This request is complete.')).toBeVisible()
  await expect(page.locator('main')).not.toContainText('Acme Supplies')
})
