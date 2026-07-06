import { test, expect } from '@playwright/test'
import { ApiClient } from '../../lib/api-client'
import { seedMiniKB, makeChatbot } from '../../lib/factories'
import { BACKEND_URL, E2E_EMAIL, E2E_PASSWORD } from '../../lib/env'

// Area D (public chat) — the real public-widget conversation, driven at the
// API level (the widget's DOM lives inside a Shadow DOM and is brittle to
// target; see widget-config.spec.ts D1-D7 for the config/UI half, which stays
// in the `fast` project since it never chats). `llm` project: the chat turns
// go through the same real answer_query pipeline as the authed chat.spec.ts,
// so they're just as slow on CPU.

async function authed(): Promise<ApiClient> {
  const api = new ApiClient()
  await api.login(E2E_EMAIL, E2E_PASSWORD)
  return api
}

function uniqueCookie(): string {
  return `e2e-widget-${Date.now().toString(36)}-${Math.floor(performance.now())}`
}

test('D8 · public widget — config + a real conversation with a persisted session', async () => {
  const api = await authed()
  const kb = await seedMiniKB(api)
  // Generous max_tokens: the public path re-uses the same agent loop/grader
  // as chat.spec.ts CU-7.2, which needs headroom to not get truncated.
  const bot = await makeChatbot(api, { kbIds: [kb.entity.id], maxTokens: 256, abstain: false })
  try {
    // No auth for the public surface — a fresh, unauthenticated client.
    const anon = new ApiClient()

    // 1. GET public config.
    const cfg = await anon.publicConfig(bot.entity.public_key)
    expect(cfg.chatbot_id).toBe(bot.entity.id)
    expect(cfg.widget).toBeTruthy()

    // 2. POST chat — first turn opens a session (session_id omitted).
    const cookie = uniqueCookie()
    const first = (await anon.publicChat(bot.entity.public_key, {
      message: 'What is the capital of Eldoria?',
      public_session_cookie: cookie,
    })) as { session_id: string; content: string }
    expect(first.session_id).toBeTruthy()
    expect((first.content ?? '').trim().length).toBeGreaterThan(0)
    expect(first.content.toLowerCase()).toContain('marisport')

    // 3. Second turn reuses the session — the backend verifies session_id +
    // public_session_cookie together (see public_chat.py), so the SAME
    // cookie must be sent back.
    const second = (await anon.publicChat(bot.entity.public_key, {
      message: 'And what database stores the vectors?',
      session_id: first.session_id,
      public_session_cookie: cookie,
    })) as { session_id: string; content: string }
    expect(second.session_id).toBe(first.session_id)
    expect((second.content ?? '').trim().length).toBeGreaterThan(0)
  } finally {
    await bot.dispose()
    await kb.dispose()
  }
})

// D9 (rate limit) is deliberately targeted at a public_key that resolves to NO
// real chatbot: the limiter keys on (public_key, IP) and runs BEFORE the
// chatbot lookup, so every request in the burst is fast (throttled ones get
// 429 immediately; the rest 404 immediately) — none reach answer_query, so
// this stays well under the "don't slow the suite" budget despite living in
// the `llm` project next to the real conversation test above.
test('D9 · public chat rate limit — a short burst on a public_key gets 429 + Retry-After', async () => {
  const fakeKey = `e2e-burst-${Date.now().toString(36)}`
  const url = `${BACKEND_URL}/api/public/chatbots/${fakeKey}/chat`
  const attempts = 8 // > the documented burst of 5

  const responses = await Promise.all(
    Array.from({ length: attempts }, () =>
      fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: 'ping', public_session_cookie: 'e2e-burst-cookie' }),
      }),
    ),
  )

  const statuses = responses.map((r) => r.status)
  expect(statuses, `expected at least one 429 in a burst of ${attempts}; got: ${statuses}`).toContain(429)
  const throttled = responses.find((r) => r.status === 429)!
  expect(throttled.headers.get('retry-after')).toBeTruthy()
})
