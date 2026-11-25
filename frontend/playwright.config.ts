import { defineConfig } from '@playwright/test'

// Runs against the TEST environment only (frontend/e2e/env/up.ps1): web :5190, API :8100, database opetional_agents_test.
const WEB = process.env.E2E_WEB_URL ?? 'http://localhost:5190'

export default defineConfig({
  testDir: './e2e/tests',
  outputDir: './test-results',
  globalSetup: './e2e/support/global-setup.ts',
  // One database, one worker: tests change shared state (stock, cases), so they run one after another.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: WEB,
    channel: 'chrome', // the system Chrome (no browser download)
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
})
