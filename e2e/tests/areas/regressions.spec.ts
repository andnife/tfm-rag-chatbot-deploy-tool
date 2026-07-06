import { test, expect } from '@playwright/test'
import { ApiClient, ApiError } from '../../lib/api-client'
import { makeKB, makeCredential } from '../../lib/factories'
import { E2E_EMAIL, E2E_PASSWORD } from '../../lib/env'

// Regression suite — locks in the 2026-06-22 bugfixes found during manual
// testing. No LLM needed, so this runs in the `fast` project.

async function authed(): Promise<ApiClient> {
  const api = new ApiClient()
  await api.login(E2E_EMAIL, E2E_PASSWORD)
  return api
}

const uniq = () => `${Date.now().toString(36)}-${Math.floor(performance.now())}`

test('R1 (CU-2.6) · saving a credential with an internal base_url → rejected (SSRF)', async () => {
  const api = await authed()
  for (const base of ['http://127.0.0.1:8000/v1', 'http://169.254.169.254/latest/meta-data']) {
    const err = await api
      .createCredential({ provider_id: 'openai_compat', label: `e2e-ssrf-${uniq()}`, api_key: 'sk-x', base_url: base })
      .catch((e) => e)
    expect(err, `expected rejection for ${base}`).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(400)
  }
})

test('R2 (CU-2.6) · a public base_url is still accepted (no over-blocking)', async () => {
  const api = await authed()
  const { entity, dispose } = await makeCredential(api, {
    provider_id: 'openai_compat',
    label: `e2e-pub-${uniq()}`,
    base_url: 'https://api.groq.com/openai/v1',
  })
  try {
    expect(entity.id).toBeTruthy()
  } finally {
    await dispose()
  }
})

test('R3 (CU-1.4) · registering an existing email → 409', async () => {
  const api = new ApiClient()
  const err = await api.register(E2E_EMAIL, E2E_PASSWORD).catch((e) => e)
  expect(err).toBeInstanceOf(ApiError)
  expect((err as ApiError).status).toBe(409)
})

test('R4 (CU-2.4) · testing a credential with a bad key → friendly message, not raw httpx', async () => {
  const api = await authed()
  const { entity: cred, dispose } = await makeCredential(api, { provider_id: 'openai', api_key: 'sk-definitely-invalid' })
  try {
    const res = (await api.testCredential(cred.id, 'gpt-4o')) as { ok: boolean; error: string | null }
    expect(res.ok).toBe(false)
    expect(res.error ?? '').not.toContain('developer.mozilla.org') // the raw httpx hint
    expect(res.error ?? '').not.toContain('https://')
  } finally {
    await dispose()
  }
})

test('R5 (CU-3.10) · KB edit shows a Save button without expanding "Avanzado"', async ({ page }) => {
  const api = await authed()
  const { entity: kb, dispose } = await makeKB(api, { name: `e2e-r5-${uniq()}` })
  try {
    await page.goto(`/knowledge/${kb.id}`)
    // The KB detail page opens on the "Fuentes" tab; the name/description editor
    // lives under the "Settings" tab.
    await page.getByRole('tab', { name: 'Settings' }).click()
    // Save button must be visible without expanding "Avanzado" (it used to be
    // trapped inside the collapsed AdvancedSection — CU-3.10).
    await expect(page.getByRole('button', { name: 'Guardar' })).toBeVisible({ timeout: 15_000 })
  } finally {
    await dispose()
  }
})

test('R6 (CU-2.7) · SERVER_ENV credential row exposes no delete button', async ({ page }) => {
  await page.goto('/settings/credentials')
  // The default Ollama credential is SERVER_ENV → only the "Probar" (test)
  // button; edit and delete must be hidden.
  const serverRow = page.locator('tr', { hasText: 'SERVER_ENV' }).first()
  await expect(serverRow).toBeVisible({ timeout: 15_000 })
  await expect(serverRow.getByRole('button')).toHaveCount(1)
})

// CU-4.1 (DB-connect dialog no longer crashes on a backend error) is covered by
// the try-catch fix in AddDatabaseSourceDialog; a UI regression test is omitted
// because the dialog's inputs aren't label-associated (brittle to target).
