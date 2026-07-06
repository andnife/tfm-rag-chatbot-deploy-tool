import { test, expect } from '@playwright/test'
import { ApiClient, ApiError } from '../../lib/api-client'
import { makeKB, makeChatbot, expectGone } from '../../lib/factories'
import { E2E_EMAIL, E2E_PASSWORD } from '../../lib/env'

// Area C — chatbots (CRUD / validation; chat lives in the llm project).

async function authed(): Promise<ApiClient> {
  const api = new ApiClient()
  await api.login(E2E_EMAIL, E2E_PASSWORD)
  return api
}

test('C1 · list chatbots + heading renders', async ({ page }) => {
  const api = await authed()
  expect(Array.isArray(await api.listChatbots())).toBe(true)
  await page.goto('/chatbots')
  await expect(page.getByRole('heading', { name: 'Chatbots' })).toBeVisible({ timeout: 15_000 })
})

test('C2 · create chatbot → appears (UI + API)', async ({ page }) => {
  const api = await authed()
  const { entity: kb, dispose: disposeKb } = await makeKB(api)
  const { entity: bot, dispose: disposeBot } = await makeChatbot(api, {
    kbIds: [kb.id],
    name: `e2e-c2-${Date.now().toString(36)}`,
  })
  try {
    const bots = (await api.listChatbots()) as Array<{ id: string }>
    expect(bots.some((b) => b.id === bot.id)).toBe(true)
    expect(bot.public_key).toBeTruthy()
    await page.goto('/chatbots')
    await expect(page.getByText(bot.name, { exact: false })).toBeVisible({ timeout: 15_000 })
  } finally {
    await disposeBot()
    await disposeKb()
  }
})

test('C2 ✗ · create chatbot with empty name → 4xx', async () => {
  const api = await authed()
  const err = await api.createChatbot({ name: '', system_prompt: 'x', kb_ids: [] }).catch((e) => e)
  expect(err).toBeInstanceOf(ApiError)
  expect((err as ApiError).status).toBeGreaterThanOrEqual(400)
  expect((err as ApiError).status).toBeLessThan(500)
})

test('C3 · edit chatbot name persists', async () => {
  const api = await authed()
  const { entity: kb, dispose: disposeKb } = await makeKB(api)
  const { entity: bot, dispose: disposeBot } = await makeChatbot(api, { kbIds: [kb.id] })
  try {
    await api.updateChatbot(bot.id, { name: 'e2e-bot-renamed' })
    expect((await api.getChatbot(bot.id)).name).toBe('e2e-bot-renamed')
  } finally {
    await disposeBot()
    await disposeKb()
  }
})

test('C4 · delete chatbot → 404 afterwards', async () => {
  const api = await authed()
  const { entity: kb, dispose: disposeKb } = await makeKB(api)
  const { entity: bot } = await makeChatbot(api, { kbIds: [kb.id] })
  await api.deleteChatbot(bot.id)
  await expectGone(() => api.getChatbot(bot.id))
  await disposeKb()
})

test('C5 · sessions empty for a fresh chatbot', async () => {
  const api = await authed()
  const { entity: kb, dispose: disposeKb } = await makeKB(api)
  const { entity: bot, dispose: disposeBot } = await makeChatbot(api, { kbIds: [kb.id] })
  try {
    expect(await api.listSessions(bot.id)).toEqual([])
  } finally {
    await disposeBot()
    await disposeKb()
  }
})
