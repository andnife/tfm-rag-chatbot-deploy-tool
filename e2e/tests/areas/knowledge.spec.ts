import { test, expect } from '@playwright/test'
import { ApiClient, ApiError } from '../../lib/api-client'
import { makeKB, makeChatbot, expectGone } from '../../lib/factories'
import { E2E_EMAIL, E2E_PASSWORD } from '../../lib/env'

// Area B — knowledge bases (CRUD / validation / errors; ingestion lives in the
// llm project's ingestion.spec.ts).

async function authed(): Promise<ApiClient> {
  const api = new ApiClient()
  await api.login(E2E_EMAIL, E2E_PASSWORD)
  return api
}

test('B1 · list KBs + heading renders', async ({ page }) => {
  const api = await authed()
  expect(Array.isArray(await api.listKBs())).toBe(true)
  await page.goto('/knowledge')
  await expect(page.getByRole('heading', { name: 'Knowledge Bases' })).toBeVisible({ timeout: 15_000 })
})

test('B2 · create KB → appears in list (UI + API)', async ({ page }) => {
  const api = await authed()
  const { entity: kb, dispose } = await makeKB(api, { name: `e2e-b2-${Date.now().toString(36)}` })
  try {
    const kbs = (await api.listKBs()) as Array<{ id: string }>
    expect(kbs.some((k) => k.id === kb.id)).toBe(true)
    await page.goto('/knowledge')
    await expect(page.getByText(kb.name, { exact: false })).toBeVisible({ timeout: 15_000 })
  } finally {
    await dispose()
  }
})

test('B2 ✗ · create KB with empty name → 4xx', async () => {
  const api = await authed()
  const err = await api
    .createKB({ name: '', chunking_config: { strategy: 'fixed', chunk_size: 600, chunk_overlap: 100 } })
    .catch((e) => e)
  expect(err).toBeInstanceOf(ApiError)
  expect((err as ApiError).status).toBeGreaterThanOrEqual(400)
  expect((err as ApiError).status).toBeLessThan(500)
})

test('B3 ✗ · get missing KB → 404', async () => {
  const api = await authed()
  const err = await api.getKB('00000000-0000-0000-0000-000000000000').catch((e) => e)
  expect(err).toBeInstanceOf(ApiError)
  expect((err as ApiError).status).toBe(404)
})

test('B10 · edit KB name persists', async () => {
  const api = await authed()
  const { entity: kb, dispose } = await makeKB(api)
  try {
    await api.updateKB(kb.id, { name: 'e2e-renamed' })
    const updated = await api.getKB(kb.id)
    expect(updated.kb.name).toBe('e2e-renamed')
  } finally {
    await dispose()
  }
})

test('B11 · delete KB ✓; delete KB in use → 409', async () => {
  const api = await authed()
  const { entity: kb } = await makeKB(api)
  const { entity: bot, dispose: disposeBot } = await makeChatbot(api, { kbIds: [kb.id] })
  // In use by a chatbot → 409.
  const err = await api.deleteKB(kb.id).catch((e) => e)
  expect(err).toBeInstanceOf(ApiError)
  expect((err as ApiError).status).toBe(409)
  // Remove the chatbot, wait until it's actually gone (delete commits
  // eventually), then the KB deletes cleanly.
  await disposeBot()
  await expectGone(() => api.getChatbot(bot.id))
  await api.deleteKB(kb.id)
  await expectGone(() => api.getKB(kb.id))
})
