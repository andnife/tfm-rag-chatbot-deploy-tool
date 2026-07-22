import { defineConfig } from '@playwright/test'

// Standalone config to VALIDATE the live defense demo (not the CI suite).
// Drives the real demo account on the running next-dev :3001 — exactly the
// path used during the defense — and records a video + screenshots that double
// as the "safety-net screencast" from the runbook.
//
// Run:  cd e2e && npx playwright test --config=demo-validate.config.ts
const BASE = process.env.DEMO_URL ?? 'http://localhost:3001'

export default defineConfig({
  testDir: './tests-demo',
  globalSetup: undefined,
  globalTeardown: undefined,
  timeout: 300_000, // chat can take ~15-25s warm; generous headroom
  expect: { timeout: 40_000 },
  retries: 0,
  workers: 1,
  fullyParallel: false,
  outputDir: './demo-artifacts',
  reporter: [['list']],
  use: {
    baseURL: BASE,
    video: 'on', // <- the screencast
    screenshot: 'on',
    trace: 'on',
    viewport: { width: 1440, height: 900 },
  },
})
