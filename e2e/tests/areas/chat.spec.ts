import { test, expect } from '@playwright/test'
import { ApiClient } from '../../lib/api-client'
import { seedMiniKB, makeChatbot } from '../../lib/factories'
import { E2E_EMAIL, E2E_PASSWORD } from '../../lib/env'

// Area — chat / RAG pipeline (real llama3.1 on CPU; slow). `llm` project.
// The fixture doc states: "The capital of the fixture country Eldoria is
// Marisport." — a fact only retrieval can supply.

async function authed(): Promise<ApiClient> {
  const api = new ApiClient()
  await api.login(E2E_EMAIL, E2E_PASSWORD)
  return api
}

test('CU-7.2 · docs route — answers from the document with citations', async () => {
  const api = await authed()
  const kb = await seedMiniKB(api)
  // max_tokens generous enough for the grader's forced tool-call (the GRADE
  // step reuses pipeline.generation; too low truncates it). abstain=false so
  // the docs route synthesises from the retrieved context instead of deferring
  // to llama3.1's over-strict "insufficient" grading (a small-model limitation).
  const bot = await makeChatbot(api, { kbIds: [kb.entity.id], maxTokens: 256, abstain: false })
  try {
    const res = (await api.chat(bot.entity.id, { message: 'What is the capital of Eldoria?' })) as {
      session_id: string
      content: string
      citations: unknown[]
    }
    expect(res.session_id).toBeTruthy()
    expect((res.content ?? '').trim().length).toBeGreaterThan(3)
    expect(Array.isArray(res.citations)).toBe(true)
    expect(res.citations.length).toBeGreaterThan(0)
    // Grounded answer surfaces the retrieved fact.
    expect(res.content.toLowerCase()).toContain('marisport')

    // The conversation is now listed as a session for the chatbot (CU-8.1).
    const sessions = (await api.listSessions(bot.entity.id)) as unknown[]
    expect(sessions.length).toBeGreaterThan(0)
  } finally {
    await bot.dispose()
    await kb.dispose()
  }
})

test('CU-7.10 · multi-turn — a follow-up reuses the session', async () => {
  const api = await authed()
  const kb = await seedMiniKB(api)
  const bot = await makeChatbot(api, { kbIds: [kb.entity.id], maxTokens: 48 })
  try {
    const first = (await api.chat(bot.entity.id, { message: 'What is the capital of Eldoria?' })) as {
      session_id: string
    }
    const second = (await api.chat(bot.entity.id, {
      message: 'And what database stores the vectors?',
      session_id: first.session_id,
    })) as { session_id: string; content: string }
    expect(second.session_id).toBe(first.session_id)
    expect((second.content ?? '').trim().length).toBeGreaterThan(3)
  } finally {
    await bot.dispose()
    await kb.dispose()
  }
})
