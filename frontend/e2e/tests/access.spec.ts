import { expect, test } from '@playwright/test'
import { ADMIN, ALL_ACCOUNTS, API, MANAGER, REQUESTER, REQUESTER2 } from '../support/accounts'
import { can, READ_ENDPOINTS } from '../support/access-model'
import { apiAs, createCaseAs } from '../support/api'
import { requestAndGetQuotationEmails, signedOutPage, suppliersQuote } from '../support/flows'
import { clearMail, decisionLink, waitForMail } from '../support/mail'
import { exactRequest, login, settle } from '../support/session'

test.beforeEach(() => clearMail())

test.describe('the server enforces who may read what (not just the menu)', () => {
  for (const account of ALL_ACCOUNTS) {
    test(`${account}`, async () => {
      const api = await apiAs(account)
      for (const { path, permission } of READ_ENDPOINTS) {
        const res = await api.get(path)
        expect(res.status(), `${account} GET ${path} (needs ${permission})`).toBe(can(account, permission) ? 200 : 403)
      }
      await api.dispose()
    })
  }

  test('nobody can read anything without signing in', async ({ request }) => {
    for (const { path } of READ_ENDPOINTS) {
      const res = await request.get(`${API}${path}`)
      expect(res.status(), path).toBe(401)
    }
  })
})

test.describe('a requester sees only their own requests', () => {
  test('another requester gets 404, on the API and on the screen; staff can see it', async ({ page, browser }) => {
    test.setTimeout(180_000)
    const { caseId, rfqs } = await requestAndGetQuotationEmails(page, 'Filing cabinets', 3, REQUESTER)
    suppliersQuote(rfqs, { acme: 90_000, globex: 95_000, initech: 99_000 })
    await waitForMail({ subject: /Approval needed/ }, 1)

    // the owner's view: no prices, no suppliers, no reasons anywhere in what the server sends
    const owner = await apiAs(REQUESTER)
    const own = await owner.get(`/cases/${caseId}`)
    expect(own.status()).toBe(200)
    const events = await owner.get(`/cases/${caseId}/events`)
    expect(events.status()).toBe(200)
    const seen = JSON.stringify([await own.json(), await events.json()])
    for (const secret of ['Acme', 'Globex', 'Initech', '90000', '90,000', '95,000', 'auto-approve limit']) expect(seen, `owner sees "${secret}"`).not.toContain(secret)
    expect((await owner.get('/cases')).status()).toBe(200)
    await owner.dispose()

    // someone else's request is "not found", never "forbidden" (it must not even confirm that it exists)
    const other = await apiAs(REQUESTER2)
    for (const path of [`/cases/${caseId}`, `/cases/${caseId}/events`]) expect((await other.get(path)).status(), path).toBe(404)
    const list = await (await other.get('/cases')).json()
    expect(JSON.stringify(list).toLowerCase()).not.toContain(caseId)
    await other.dispose()

    const ctx = await browser.newContext()
    const p2 = await ctx.newPage()
    await login(p2, REQUESTER2)
    await p2.goto(`/requests/${caseId}`)
    await settle(p2)
    await expect(p2.locator('main')).not.toContainText('Filing cabinets')
    await expect(p2.locator('main')).not.toContainText('Acme')
    await ctx.close()

    // staff see the whole case
    const staff = await apiAs(ADMIN)
    expect((await staff.get(`/cases/${caseId}`)).status()).toBe(200)
    await staff.dispose()
  })

  test('a requester cannot open staff pages: no table of data, only a refusal or a redirect', async ({ page }) => {
    await login(page, REQUESTER)
    for (const path of ['/stock', '/vendors', '/approvals', '/users', '/audit', '/cases', '/dashboard', '/store-room', '/my-work']) {
      await page.goto(path)
      await settle(page)
      await expect(page.locator('table'), `${path} shows a table of data`).toHaveCount(0)
    }
  })

  test("a requester cannot file a request in someone else's name", async () => {
    const api = await apiAs(REQUESTER)
    const { text } = exactRequest('Whiteboards', 1)
    const res = await api.post('/cases', { data: { raw_request: text, requester_id: REQUESTER2 } })
    expect(res.ok()).toBe(true)
    const caseId = (await res.json()).case_id
    const other = await apiAs(REQUESTER2)
    expect((await other.get(`/cases/${caseId}`)).status()).toBe(404)
    await api.dispose()
    await other.dispose()
  })
})

test.describe('nobody approves their own request', () => {
  test('the manager files a request: their own approval link and API call are refused; the admin can approve', async ({ browser }) => {
    test.setTimeout(180_000)
    const { text, item } = exactRequest('Conference tables', 4)
    const caseId = await createCaseAs(MANAGER, text)
    const rfqs = await waitForMail({ subject: `[OA-${caseId}] Request for quotation` }, 3)
    suppliersQuote(rfqs, { acme: 90_000, globex: 95_000, initech: 99_000 })
    const approvals = await waitForMail({ subject: /Approval needed/ }, 2)
    const mine = approvals.find((m) => m.to === 'manager@e2e.test')!
    const adminsMail = approvals.find((m) => m.to === 'admin@e2e.test')!
    expect(mine.body).toContain(item)

    // the manager's emailed link opens, but offers no way to approve
    const { page, close } = await signedOutPage(browser)
    await page.goto(decisionLink(mine, 'approve'))
    await settle(page)
    await expect(page.getByRole('button', { name: 'Yes, approve' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Approve', exact: true })).toHaveCount(0)
    await close()

    // the manager calling the server directly is refused too
    const api = await apiAs(MANAGER)
    const list = (await (await api.get('/approvals')).json()) as any[]
    const approval = list.find((a) => String(a.case_id).toLowerCase() === caseId)
    expect(approval, 'the manager can see the approval').toBeTruthy()
    const res = await api.post(`/approvals/${approval.approval_id ?? approval.id}/approve`, { data: {} })
    expect(res.status()).toBeGreaterThanOrEqual(400)
    expect(res.status()).toBeLessThan(500)
    expect(await res.text()).toMatch(/someone else/i)
    await api.dispose()

    // a different person's link works
    const second = await signedOutPage(browser)
    await second.page.goto(decisionLink(adminsMail, 'approve'))
    await second.page.getByRole('button', { name: 'Yes, approve' }).click()
    await expect(second.page.getByRole('heading', { name: 'Approved' })).toBeVisible()
    await second.close()
    await waitForMail({ subject: /Purchase Order PO-/ })
  })
})
