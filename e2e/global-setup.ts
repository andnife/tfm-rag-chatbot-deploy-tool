// Runs once before the suite: bring up the mirror, verify the stack is healthy,
// ensure the dedicated e2e user exists, and save its logged-in cookie state.
import { chromium, type FullConfig } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { ApiClient } from './lib/api-client'
import { startMirror } from './lib/mirror'
import { BASE_URL, E2E_EMAIL, E2E_PASSWORD, STORAGE_STATE } from './lib/env'
import { S } from './lib/selectors'

export default async function globalSetup(_config: FullConfig): Promise<void> {
  await startMirror()

  const api = new ApiClient()
  const health = await api.health().catch((e) => {
    throw new Error(`backend not reachable — start the stack first (scripts/e2e.sh). ${e}`)
  })
  if (health.status !== 'ok' && health.status !== 'degraded') {
    throw new Error(`backend health not ok: ${JSON.stringify(health)}`)
  }

  // Ensure the e2e user exists (register is idempotent-ish: 409 if already there).
  try {
    await api.register(E2E_EMAIL, E2E_PASSWORD)
  } catch (e: any) {
    if (e?.status !== 409) throw e
  }

  // Save logged-in cookie state by driving the real login form (sets the httpOnly
  // cookie the middleware checks).
  mkdirSync(path.dirname(STORAGE_STATE), { recursive: true })
  const browser = await chromium.launch()
  const page = await browser.newPage({ baseURL: BASE_URL })
  await page.goto('/login')
  await page.getByLabel(S.login.email).fill(E2E_EMAIL)
  await page.getByLabel(S.login.password).fill(E2E_PASSWORD)
  await page.getByRole('button', { name: S.login.submit }).click()
  await page.waitForURL(/\/dashboard/, { timeout: 15_000 })
  await page.context().storageState({ path: STORAGE_STATE })
  await browser.close()
}
