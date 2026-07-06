import { test, expect } from '@playwright/test'
import { ApiClient } from '../../lib/api-client'
import { makeKB, makeChatbot } from '../../lib/factories'
import { countSqlSourceRows, seedSqlSource } from '../../lib/db'
import { E2E_EMAIL, E2E_PASSWORD } from '../../lib/env'

// Area — SQL route (real llama3.1 agent loop against a live Postgres "source"
// database; slow on CPU). `llm` project. Mirrors backend's own
// tests/integration/test_chat_sql_flow.py: attach a DatabaseSource to a KB,
// then ask a question only the DB can answer, and separately prove a
// destructive request can't mutate it (sql_safety.assert_select_only + the
// connector's read-only transaction).

async function authed(): Promise<ApiClient> {
  const api = new ApiClient()
  await api.login(E2E_EMAIL, E2E_PASSWORD)
  return api
}

test('CU-7.7 · sql route — answers using data from an attached database', async () => {
  const api = await authed()
  const kb = await makeKB(api, { name: `e2e-sql-${Date.now().toString(36)}` })
  try {
    // seedSqlSource() runs raw pg.Client + DDL and can throw — nest it inside
    // the kb's try/finally so a failure here still disposes the KB.
    const source = await seedSqlSource()
    try {
      const check = await api.testDbConnection(kb.entity.id, { type: 'database', spec: source.spec })
      expect(check.ok).toBe(true)

      const attached = await api.attachDatabase(kb.entity.id, source.spec)
      expect(attached.snapshot_tables).toBeGreaterThanOrEqual(1)

      const bot = await makeChatbot(api, {
        kbIds: [kb.entity.id],
        maxTokens: 256,
        abstain: false,
        name: `e2e-sql-bot-${Date.now().toString(36)}`,
      })
      try {
        const res = (await api.chat(bot.entity.id, {
          message: 'How many rows are in the e2e_products table? Use the database to check.',
        })) as { content: string; iterations?: Array<{ tool?: string }> }
        const tools = (res.iterations ?? []).map((it) => it.tool)
        const usedDbRoute = tools.includes('sql') || tools.includes('both')
        // Lenient like the backend's own SQL-route integration test: either the
        // router visibly took a sql/both iteration, or the exact row count
        // (a fact only the DB supplies) shows up in the answer.
        expect(
          usedDbRoute || res.content.includes(String(source.rowCount)),
          `expected a sql/both iteration or the row count in the answer; got: ${JSON.stringify(res)}`,
        ).toBe(true)
      } finally {
        await bot.dispose()
      }
    } finally {
      await source.dispose()
    }
  } finally {
    await kb.dispose()
  }
})

test('CU-7.8 · sql safety — a destructive request does not mutate the database', async () => {
  const api = await authed()
  const kb = await makeKB(api, { name: `e2e-sql-safety-${Date.now().toString(36)}` })
  try {
    // seedSqlSource() runs raw pg.Client + DDL and can throw — nest it inside
    // the kb's try/finally so a failure here still disposes the KB.
    const source = await seedSqlSource()
    try {
      await api.attachDatabase(kb.entity.id, source.spec)

      const bot = await makeChatbot(api, {
        kbIds: [kb.entity.id],
        maxTokens: 128,
        name: `e2e-sql-safety-bot-${Date.now().toString(36)}`,
      })
      try {
        // We can't force the LLM to emit DDL/DML — this exercises the same path
        // CU-7.8 does manually: either the router doesn't pick `sql` for a
        // destructive ask, the generator only ever emits SELECT, or
        // sql_safety.assert_select_only blocks it. Any of those is a pass; a
        // 200 response plus an untouched row count is what must hold.
        const res = await api.chat(bot.entity.id, { message: 'Delete all rows from the e2e_products table.' })
        expect(res.session_id).toBeTruthy()

        const rows = await countSqlSourceRows()
        expect(rows).toBe(source.rowCount)
      } finally {
        await bot.dispose()
      }
    } finally {
      await source.dispose()
    }
  } finally {
    await kb.dispose()
  }
})
