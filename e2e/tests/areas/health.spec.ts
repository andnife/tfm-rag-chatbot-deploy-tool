import { test, expect } from '@playwright/test'
import { ApiClient } from '../../lib/api-client'

// Area H — health / infra. Pure API (no UI), fast project.
test.describe('H · health & infra', () => {
  test('H · GET /health reports ok|degraded with components', async () => {
    const api = new ApiClient()
    const health = await api.health()
    expect(['ok', 'degraded']).toContain(health.status)
    expect(Array.isArray(health.components)).toBe(true)
    expect(health.components.length).toBeGreaterThan(0)
  })

  test('H · GET /api/ollama/models lists local models', async () => {
    const api = new ApiClient()
    await api.login(process.env.E2E_EMAIL ?? 'e2e@test.com', process.env.E2E_PASSWORD ?? 'E2eTest1234!')
    const res = await api.ollamaModels()
    expect(Array.isArray(res.models)).toBe(true)
    // llama3.1 + bge-m3 must be pulled for the llm specs to work
    const names = (res.models as Array<{ name: string }>).map((m) => m.name)
    expect(names.some((n) => n.startsWith('llama3.1'))).toBe(true)
  })
})
