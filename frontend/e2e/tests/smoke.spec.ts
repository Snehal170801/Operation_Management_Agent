import { expect, test } from '@playwright/test'
import { ALL_ACCOUNTS } from '../support/accounts'
import { hasHorizontalScroll, login, settle } from '../support/session'
import { EXPECTED_NOISE, watchProblems } from '../support/watch'

const VIEWPORTS = [{ width: 1440, height: 900 }, { width: 390, height: 844 }]
// Before sign-in the app asks for a session and gets the normal "not signed in" 401.
// The live-update stream (SSE) is cut off whenever the test moves to another page: that is normal.
const NOT_SIGNED_IN = EXPECTED_NOISE

test.describe('public pages', () => {
  for (const path of ['/login', '/forgot-password']) {
    for (const vp of VIEWPORTS) {
      test(`${path} loads cleanly at ${vp.width}px`, async ({ page }) => {
        const problems = watchProblems(page, NOT_SIGNED_IN)
        await page.setViewportSize(vp)
        await page.goto(path)
        await expect(page.locator('form')).toBeVisible()
        expect(await hasHorizontalScroll(page)).toBe(false)
        expect(problems).toEqual([])
      })
    }
  }
})

test('a wrong password is refused and says so', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email or username').fill('admin')
  await page.getByLabel('Password', { exact: true }).fill('not-the-password')
  await page.getByRole('button', { name: /sign in|log in/i }).click()
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByRole('alert').or(page.getByText(/incorrect|invalid|wrong/i)).first()).toBeVisible()
})

test.describe('every account opens every page it may see', () => {
  for (const username of ALL_ACCOUNTS) {
    test(`${username}`, async ({ page }) => {
      const problems = watchProblems(page, NOT_SIGNED_IN)
      await page.setViewportSize(VIEWPORTS[0])
      await login(page, username)
      await settle(page)

      const links = await page.locator('a[href^="/"]').evaluateAll((els) =>
        [...new Set(els.map((a) => (a as HTMLAnchorElement).getAttribute('href')!))].filter((h) => !h.startsWith('/decide')))
      expect(links.length, 'the menu has pages').toBeGreaterThan(0)
      expect(links).toContain('/settings')

      for (const vp of VIEWPORTS) {
        await page.setViewportSize(vp)
        for (const href of links) {
          await page.goto(href)
          await settle(page)
          await expect(page.locator('main, [role="main"], #root').first()).toBeVisible()
          await expect(page.getByText(/page not found|something went wrong|no access/i), `${href} @${vp.width}`).toHaveCount(0)
          expect(await hasHorizontalScroll(page), `horizontal scroll on ${href} at ${vp.width}px`).toBe(false)
        }
      }
      expect(problems).toEqual([])
    })
  }
})
