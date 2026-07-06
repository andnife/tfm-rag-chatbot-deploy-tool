import { test, expect } from '@playwright/test'
import { ApiClient, ApiError } from '../../lib/api-client'
import { S } from '../../lib/selectors'
import { E2E_EMAIL, E2E_PASSWORD } from '../../lib/env'

// Area A — auth. UI for the gated/login flows; api-client for the deterministic
// error paths (validation/409/401) that don't depend on guessing ES toast text.

// Anonymous context for everything here (no stored cookie).
test.use({ storageState: { cookies: [], origins: [] } })

function uniqueEmail(): string {
  _ctr += 1
  return `e2e-reg-${Date.now().toString(36)}-${_ctr}@test.com`
}
let _ctr = 0

test('A1 · register ✓ (new tenant)', async () => {
  const api = new ApiClient()
  const r = await api.register(uniqueEmail(), 'Str0ngPass!')
  expect(r.access_token).toBeTruthy()
  expect(r.tenant_id).toBeTruthy()
})

test('A1 ✗ · register with short password → 4xx', async () => {
  const api = new ApiClient()
  const err = await api.register(uniqueEmail(), 'short').catch((e) => e)
  expect(err).toBeInstanceOf(ApiError)
  expect((err as ApiError).status).toBeGreaterThanOrEqual(400)
  expect((err as ApiError).status).toBeLessThan(500)
})

test('A1 ✗ · register duplicate email → 409', async () => {
  const api = new ApiClient()
  const err = await api.register(E2E_EMAIL, E2E_PASSWORD).catch((e) => e)
  expect(err).toBeInstanceOf(ApiError)
  expect((err as ApiError).status).toBe(409)
})

test('A2 · login ✓ via UI → /dashboard', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel(S.login.email).fill(E2E_EMAIL)
  await page.getByLabel(S.login.password).fill(E2E_PASSWORD)
  await page.getByRole('button', { name: S.login.submit }).click()
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 })
})

test('A2 ✗ · login wrong password → 401 + stays on /login', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel(S.login.email).fill(E2E_EMAIL)
  await page.getByLabel(S.login.password).fill('definitely-wrong')
  await page.getByRole('button', { name: S.login.submit }).click()
  // Never navigates to the dashboard; stays on /login.
  await page.waitForTimeout(2000)
  await expect(page).toHaveURL(/\/login/)
})

test('A5 · gated route while anonymous → /login', async ({ page }) => {
  await page.goto('/dashboard')
  await expect(page).toHaveURL(/\/login/, { timeout: 15_000 })
})

test('A6 · garbage cookie → /login', async ({ page, context }) => {
  await context.addCookies([
    { name: 'tfm_rag_token', value: 'garbage.invalid.jwt', url: 'http://localhost:8080' },
  ])
  await page.goto('/knowledge')
  await expect(page).toHaveURL(/\/login/, { timeout: 15_000 })
})
