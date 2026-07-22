import { defineConfig } from '@playwright/test'

// Regression for the "Console" delivery snippet: injecting widget.js dynamically
// (document.currentScript === null) must still mount the widget via the
// data-tfm-widget fallback selector.
const BASE = process.env.DEMO_URL ?? 'http://localhost:3001'

export default defineConfig({
  testDir: './tests-widget',
  timeout: 120_000,
  expect: { timeout: 30_000 },
  retries: 0,
  workers: 1,
  outputDir: './demo-artifacts/widget-console',
  reporter: [['list']],
  use: { baseURL: BASE, video: 'on', screenshot: 'on', trace: 'on', viewport: { width: 1200, height: 800 } },
})
