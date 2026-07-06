import path from 'node:path'
import { test, expect } from '@playwright/test'
import { ApiClient } from '../../lib/api-client'
import { makeKB } from '../../lib/factories'
import { E2E_EMAIL, E2E_PASSWORD } from '../../lib/env'

// Area — document ingestion (real embeddings via Ollama bge-m3). Lives in the
// `llm` project because it waits on the model. Exercises the granular-progress
// pipeline end to end (job reaches done with progress 100).

const DOCS = path.resolve(__dirname, '../../fixtures/docs')

async function authed(): Promise<ApiClient> {
  const api = new ApiClient()
  await api.login(E2E_EMAIL, E2E_PASSWORD)
  return api
}

test('CU-3.6 · upload a TXT → ingestion reaches done (progress 100) and is searchable', async () => {
  const api = await authed()
  const { entity: kb, dispose } = await makeKB(api, { name: `e2e-ingest-${Date.now().toString(36)}` })
  try {
    const up = await api.uploadDocument(kb.id, path.join(DOCS, 'sample.txt'))
    expect(up.job_id).toBeTruthy()

    const job = await api.waitIngestion(up.job_id)
    expect(job.status).toBe('done')
    expect(job.progress).toBe(100)

    // Embeddings landed in Qdrant → a relevant query returns at least one hit.
    const hits = (await api.searchKB(kb.id, { query: 'capital of Eldoria', top_k: 3 })) as
      | { hits?: unknown[] }
      | unknown[]
    const arr = Array.isArray(hits) ? hits : (hits.hits ?? [])
    expect(arr.length).toBeGreaterThan(0)
  } finally {
    await dispose()
  }
})

test('CU-3.8 · uploading an unsupported file type → rejected or job fails with an error', async () => {
  const api = await authed()
  const { entity: kb, dispose } = await makeKB(api, { name: `e2e-ingest-bad-${Date.now().toString(36)}` })
  try {
    // Either the upload is rejected up front (4xx) or the background job fails
    // with a legible error — both are acceptable; what must NOT happen is a
    // silent "done".
    let jobId: string | undefined
    try {
      const up = await api.uploadDocument(kb.id, path.join(DOCS, 'unsupported.bin'))
      jobId = up.job_id
    } catch (e: any) {
      expect(e.status).toBeGreaterThanOrEqual(400)
      expect(e.status).toBeLessThan(500)
      return
    }
    const job = await api.waitIngestion(jobId!)
    expect(job.status).toBe('failed')
    expect(job.error ?? '').not.toBe('')
  } finally {
    await dispose()
  }
})
