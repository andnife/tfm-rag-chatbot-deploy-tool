import { defineConfig } from '@playwright/test'

// Standalone exploratory QA crawl (separate from the demo-validation config).
// Visits every reachable route as a throwaway account, captures a screenshot
// per route and records anomalies (console errors, pageerrors, HTTP >=400,
// unexpected redirects). Read-only-ish: it never sends a chat message.
const BASE = process.env.DEMO_URL ?? 'http://localhost:3001'

export default defineConfig({
  testDir: './tests-explore',
  timeout: 300_000,
  expect: { timeout: 30_000 },
  retries: 0,
  workers: 1,
  fullyParallel: false,
  outputDir: './demo-artifacts/explore',
  reporter: [['list']],
  use: {
    baseURL: BASE,
    video: 'on',
    screenshot: 'off', // we take explicit, fully-loaded screenshots ourselves
    trace: 'on',
    viewport: { width: 1440, height: 900 },
  },
})
