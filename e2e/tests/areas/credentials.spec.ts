import { test, expect } from '@playwright/test'
import { ApiClient, ApiError } from '../../lib/api-client'
import { makeCredential } from '../../lib/factories'
import { E2E_EMAIL, E2E_PASSWORD } from '../../lib/env'

// Area F — credentials. API-driven for the deterministic CRUD/test paths; a UI
// render check that a created credential shows up on /settings/credentials.

async function authed(): Promise<ApiClient> {
  const api = new ApiClient()
  await api.login(E2E_EMAIL, E2E_PASSWORD)
  return api
}

test('F1 · list credentials returns the tenant set', async () => {
  const api = await authed()
  const creds = (await api.listCredentials()) as unknown[]
  expect(Array.isArray(creds)).toBe(true) // at least the synthetic ollama credential
})

test('F2/F5 · create then delete a credential', async () => {
  const api = await authed()
  const { entity } = await makeCredential(api, { label: 'e2e-f2', api_key: 'sk-fake-123' })
  expect(entity.id).toBeTruthy()
  const after = (await api.listCredentials()) as Array<{ id: string }>
  expect(after.some((c) => c.id === entity.id)).toBe(true)
  // Delete directly (don't swallow errors via dispose) and confirm it's gone.
  await api.deleteCredential(entity.id)
  let present = true
  for (let i = 0; i < 10 && present; i++) {
    const list = (await api.listCredentials()) as Array<{ id: string }>
    present = list.some((c) => c.id === entity.id)
    if (present) await new Promise((r) => setTimeout(r, 500))
  }
  expect(present).toBe(false)
})

test('F3 · test a credential with a fake key → not ok', async () => {
  const api = await authed()
  const { entity, dispose } = await makeCredential(api, { label: 'e2e-f3', api_key: 'sk-invalid' })
  try {
    // openai provider + fake key: either a {ok:false} result or a 4xx — both mean "not ok".
    const res = await api.testCredential(entity.id, 'gpt-4o-mini').catch((e) => e)
    if (res instanceof ApiError) expect(res.status).toBeGreaterThanOrEqual(400)
    else expect(res.ok).toBe(false)
  } finally {
    await dispose()
  }
})

test('F · created credential appears on /settings/credentials', async ({ page }) => {
  const api = await authed()
  const { entity, dispose } = await makeCredential(api, { label: `e2e-ui-${Date.now().toString(36)}` })
  try {
    await page.goto('/settings/credentials')
    await expect(page.getByText(entity.label, { exact: false })).toBeVisible({ timeout: 15_000 })
  } finally {
    await dispose()
  }
})
