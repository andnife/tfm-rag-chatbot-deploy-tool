import { test, expect } from '@playwright/test'
import { ApiClient } from '../../lib/api-client'
import { makeKB, makeChatbot } from '../../lib/factories'
import { E2E_EMAIL, E2E_PASSWORD } from '../../lib/env'

// Area D (config part) — widget configuration + public config endpoint.
// The public widget CHAT (D4) is exercised by the llm widget-publish journey.

async function authed(): Promise<ApiClient> {
  const api = new ApiClient()
  await api.login(E2E_EMAIL, E2E_PASSWORD)
  return api
}

test('D1 · update widget config persists', async () => {
  const api = await authed()
  const { entity: kb, dispose: disposeKb } = await makeKB(api)
  const { entity: bot, dispose: disposeBot } = await makeChatbot(api, { kbIds: [kb.id] })
  try {
    await api.updateChatbot(bot.id, {
      widget_config: {
        theme: 'dark',
        primary_color: '#ff0000',
        position: 'bottom-left',
        title: 'E2E Widget',
        welcome_message: 'hola',
        placeholder: 'pregunta...',
        allowed_origins: ['*'],
      },
    })
    const updated = await api.getChatbot(bot.id)
    expect(updated.widget_config.title).toBe('E2E Widget')
    expect(updated.widget_config.theme).toBe('dark')
  } finally {
    await disposeBot()
    await disposeKb()
  }
})

test('D2 · widget page shows embed snippet with public_key', async ({ page }) => {
  const api = await authed()
  const { entity: kb, dispose: disposeKb } = await makeKB(api)
  const { entity: bot, dispose: disposeBot } = await makeChatbot(api, { kbIds: [kb.id] })
  try {
    await page.goto(`/chatbots/${bot.id}/widget`)
    await expect(page.getByText('widget.js', { exact: false })).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText(String(bot.public_key).slice(0, 12), { exact: false }).first()).toBeVisible()
  } finally {
    await disposeBot()
    await disposeKb()
  }
})

test('D3 · public config endpoint returns widget config', async () => {
  const api = await authed()
  const { entity: kb, dispose: disposeKb } = await makeKB(api)
  const { entity: bot, dispose: disposeBot } = await makeChatbot(api, { kbIds: [kb.id] })
  try {
    const cfg = await api.publicConfig(bot.public_key)
    expect(cfg.chatbot_id).toBe(bot.id)
    expect(cfg.widget).toBeTruthy()
  } finally {
    await disposeBot()
    await disposeKb()
  }
})

test('D5 · public config + persisted config carry welcome_message_named', async () => {
  const api = await authed()
  const { entity: kb, dispose: disposeKb } = await makeKB(api)
  const { entity: bot, dispose: disposeBot } = await makeChatbot(api, { kbIds: [kb.id] })
  try {
    await api.updateChatbot(bot.id, {
      widget_config: {
        theme: 'light',
        primary_color: '#3b82f6',
        position: 'bottom-right',
        title: 'E2E',
        welcome_message: 'Hola, ¿en qué ayudo?',
        welcome_message_named: 'Hola {name}, ¿en qué ayudo?',
        placeholder: '...',
        allowed_origins: ['*'],
      },
    })
    const updated = await api.getChatbot(bot.id)
    expect(updated.widget_config.welcome_message_named).toContain('{name}')
    const cfg = await api.publicConfig(bot.public_key)
    expect(cfg.widget.welcome_message_named).toContain('{name}')
  } finally {
    await disposeBot()
    await disposeKb()
  }
})

test('D6 · welcome-suggestions endpoint returns two greeting variants', async () => {
  // Falls back to static defaults when no LLM is reachable, so it is safe to
  // assert the shape in the fast project (named always carries {name}).
  const api = await authed()
  const { entity: kb, dispose: disposeKb } = await makeKB(api)
  const { entity: bot, dispose: disposeBot } = await makeChatbot(api, { kbIds: [kb.id] })
  try {
    const s = await api.welcomeSuggestions(bot.id)
    expect(typeof s.welcome_message).toBe('string')
    expect(s.welcome_message.length).toBeGreaterThan(0)
    expect(s.welcome_message_named).toContain('{name}')
  } finally {
    await disposeBot()
    await disposeKb()
  }
})

test('D7 · playground has Debug + Preview tabs; Preview embeds the widget', async ({ page }) => {
  const api = await authed()
  const { entity: kb, dispose: disposeKb } = await makeKB(api)
  const { entity: bot, dispose: disposeBot } = await makeChatbot(api, { kbIds: [kb.id] })
  try {
    await page.goto(`/chatbots/${bot.id}/playground`)
    const tabs = page.getByRole('tab')
    await expect(tabs).toHaveCount(2, { timeout: 15_000 })
    await tabs.nth(1).click() // Preview
    await expect(page.locator('iframe[title="widget-preview"]')).toBeVisible({ timeout: 15_000 })
  } finally {
    await disposeBot()
    await disposeKb()
  }
})
