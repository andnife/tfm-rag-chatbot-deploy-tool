import path from 'node:path'
import { test, expect } from '@playwright/test'
import { ApiClient } from '../../lib/api-client'
import { makeChatbot } from '../../lib/factories'
import { grantSuperadmin } from '../../lib/db'
import { E2E_EMAIL, E2E_PASSWORD } from '../../lib/env'

// Area — RAGAS evaluation (real chatbot answers + local Ollama judge; very slow
// on CPU). `llm` project.
//
// The entity-run flow (current): POST /api/admin/eval/datasets creates a
// dataset AND its own KB in one call; rows are imported afterwards; a run is
// then launched scoped to that dataset. The old flat, dataset_path-based
// `POST /api/admin/eval/runs` no longer exists (dropped when the judge became
// credential-first) — this spec previously called it and was dead.
//
// All /api/admin/eval/* routes also now require app-level superadmin (see
// dependencies.py `require_superadmin`), added after this spec was written.
// We grant it directly on Postgres (same trick backend/tests/integration/*
// use) and re-login so the token carries the `sa` claim.
//
// We assert the run COMPLETES and the report carries an actual numeric RAGAS
// score — not that scores are "good". To make that likely on a tiny CPU judge,
// the single row asks about a fact that really is in the ingested document
// (the fixture doc's "capital of Eldoria is Marisport"), same as chat.spec.ts.

const FIXTURE_DOC = path.resolve(__dirname, '../../fixtures/docs/sample.txt')

async function authedSuperadmin(): Promise<ApiClient> {
  const api = new ApiClient()
  await api.login(E2E_EMAIL, E2E_PASSWORD)
  // Intentionally not reverted after the test — global-teardown.ts is
  // best-effort cleanup of entities (chatbots/KBs/credentials) only, it
  // doesn't touch user flags, and the e2e tenant's superadmin grant is
  // harmless to leave set between runs.
  await grantSuperadmin(E2E_EMAIL)
  await api.login(E2E_EMAIL, E2E_PASSWORD) // refresh the token so it carries `sa: true`
  return api
}

async function waitRun(api: ApiClient, id: string, timeoutMs = 560_000): Promise<any> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const run = await api.getEvalRun(id)
    if (run.status === 'done' || run.status === 'failed') return run
    if (Date.now() > deadline) throw new Error(`eval run ${id} timed out (last: ${run.status} ${run.progress}%)`)
    await new Promise((r) => setTimeout(r, 3000))
  }
}

test('CU-11.2/11.4 · entity-dataset run → completes and the report carries a numeric RAGAS score', async () => {
  const api = await authedSuperadmin()
  const credential_id = await api.ollamaCredentialId()

  // 1. Create the dataset — this also provisions its own KB.
  const ds = await api.createEvalDataset({
    name: `e2e eval ds ${Date.now().toString(36)}`,
    description: 'e2e fixture dataset',
    embedding_selection: { provider_id: 'ollama', credential_id, model_id: 'bge-m3', dim: 1024 },
  })
  const kbId = ds.knowledge_base_id as string
  expect(kbId).toBeTruthy()

  try {
    // 2. Ingest the shared fixture doc into that KB.
    const up = await api.uploadDocument(kbId, FIXTURE_DOC)
    const job = await api.waitIngestion(up.job_id)
    expect(job.status).toBe('done')

    // 3. Import a single row whose ground truth the doc actually supports.
    const jsonl = JSON.stringify({
      question: 'What is the capital of Eldoria?',
      ground_truth: 'Marisport',
      scenario: 'doc_only',
      complexity: 'factual',
    })
    const imported = await api.importDatasetRows(ds.id, jsonl)
    expect(imported.num_rows).toBe(1)

    // 4. Chatbot wired to that same KB, configured to actually answer.
    const bot = await makeChatbot(api, { kbIds: [kbId], maxTokens: 128, abstain: false })
    try {
      // 5. Launch the run.
      const run = (await api.createEntityEvalRun(ds.id, {
        chatbot_id: bot.entity.id,
        // No `judge_provider` field: CreateEntityRunIn (eval_datasets.py) has
        // no such field — it would be silently dropped by pydantic anyway.
        judge_credential_id: credential_id,
        judge_model: 'gemma3:1b',
      })) as { id: string; status: string }
      expect(run.id).toBeTruthy()
      expect(['queued', 'running']).toContain(run.status)

      const done = await waitRun(api, run.id)
      expect(done.status).toBe('done')
      expect(done.progress).toBe(100)
      expect(done.report_dir).toBeTruthy()

      // 6. The report exists and carries at least one finite numeric metric
      // (RAGAS may legitimately return NaN for some metrics on a 1-row run —
      // we only require ONE usable score, not all four).
      const report = await api.getReportJson(done.report_dir)
      const metrics = report?.summary?.metrics as Record<string, number> | undefined
      expect(metrics, `report.json had no summary.metrics: ${JSON.stringify(report)}`).toBeTruthy()
      const values = Object.values(metrics ?? {})
      expect(
        values.some((v) => typeof v === 'number' && Number.isFinite(v)),
        `expected at least one finite metric score; got: ${JSON.stringify(metrics)}`,
      ).toBe(true)
    } finally {
      await bot.dispose()
    }
  } finally {
    // Deletes the dataset row AND its provisioned KB atomically.
    await api.deleteEvalDataset(ds.id).catch(() => {})
  }
})
