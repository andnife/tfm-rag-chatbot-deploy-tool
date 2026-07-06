// API-backed test data factories. Each returns the created entity plus a
// dispose() that deletes it, so specs stay isolated and self-cleaning.
import path from 'node:path'
import { ApiClient } from './api-client'

const FIXTURE_DOC = path.resolve(__dirname, '../fixtures/docs/sample.txt')

export interface Disposable<T> {
  entity: T
  dispose: () => Promise<void>
}

// Read-after-write is eventual here: the backend commits a write in FastAPI's
// yield-dependency teardown, i.e. just AFTER the response is sent, so an
// immediate follow-up read on another pooled connection can miss it (~3%).
// Factories confirm a created entity is visible before returning, so downstream
// reads/updates never race. (Backend race documented as a separate finding.)
async function confirmVisible(read: () => Promise<unknown>, tries = 12): Promise<void> {
  for (let i = 0; i < tries; i++) {
    try {
      await read()
      return
    } catch {
      await new Promise((r) => setTimeout(r, 250))
    }
  }
  await read() // final attempt; let the real error surface
}

/** Poll until `read()` throws an ApiError 404 (a delete commits eventually too). */
export async function expectGone(read: () => Promise<unknown>, tries = 12): Promise<void> {
  for (let i = 0; i < tries; i++) {
    const r = await read().catch((e) => e)
    if (r && typeof r === 'object' && (r as { status?: number }).status === 404) return
    await new Promise((res) => setTimeout(res, 250))
  }
  throw new Error('entity still present after delete (no 404 within timeout)')
}

/** Default local embedding (bge-m3 1024d via Ollama, no tenant credential needed). */
const EMBED = { provider_id: 'ollama', model_id: 'bge-m3', dim: 1024 }
const LLM_MODEL = 'llama3.1'

export async function makeKB(
  api: ApiClient,
  opts: { name?: string; chunkSize?: number } = {},
): Promise<Disposable<any>> {
  const credential_id = await api.ollamaCredentialId()
  const body = {
    name: opts.name ?? `e2e KB ${unique()}`,
    description: 'e2e fixture KB',
    chunking_config: { strategy: 'fixed', chunk_size: opts.chunkSize ?? 600, chunk_overlap: 100 },
    embedding_selection: { ...EMBED, credential_id },
  }
  // Concurrent KB creation can race on the shared Qdrant collection (backend
  // returns 500 wrapping a Qdrant "409 Conflict"); retry a few times.
  let kb: any
  for (let attempt = 0; ; attempt++) {
    try {
      kb = await api.createKB(body)
      break
    } catch (e: any) {
      const conflict = e?.status === 500 || e?.status === 409
      if (!conflict || attempt >= 5) throw e
      await new Promise((r) => setTimeout(r, 400 * (attempt + 1)))
    }
  }
  await confirmVisible(() => api.getKB(kb.id))
  return { entity: kb, dispose: () => api.deleteKB(kb.id).catch(() => {}) }
}

/** A KB with one ingested document, ready to retrieve from. */
export async function seedMiniKB(api: ApiClient): Promise<Disposable<any>> {
  const { entity: kb, dispose } = await makeKB(api, { name: `e2e mini KB ${unique()}` })
  const up = await api.uploadDocument(kb.id, FIXTURE_DOC)
  await api.waitIngestion(up.job_id)
  return { entity: kb, dispose }
}

/** A chatbot wired to kbIds, configured for SHORT real outputs (fast-ish on CPU). */
export async function makeChatbot(
  api: ApiClient,
  opts: { kbIds: string[]; maxTokens?: number; maxIterations?: number; name?: string; abstain?: boolean },
): Promise<Disposable<any>> {
  const credential_id = await api.ollamaCredentialId()
  const bot = await api.createChatbot({
    name: opts.name ?? `e2e bot ${unique()}`,
    description: 'e2e fixture chatbot',
    system_prompt: 'You are a test assistant. Answer briefly using the documents.',
    llm_selection: { provider_id: 'ollama', credential_id, model_id: LLM_MODEL },
    kb_ids: opts.kbIds,
    pipeline_config: {
      top_k: 5,
      score_threshold: 0.0,
      agentic_mode: true,
      max_retrieval_iterations: opts.maxIterations ?? 1,
      enable_reranker: false,
      reranker_initial_top_k: 30,
      abstain_when_insufficient: opts.abstain ?? true,
      generation: { temperature: 0.0, top_p: 1.0, max_tokens: opts.maxTokens ?? 32 },
    },
  })
  await confirmVisible(() => api.getChatbot(bot.id))
  return { entity: bot, dispose: () => api.deleteChatbot(bot.id).catch(() => {}) }
}

export async function makeCredential(
  api: ApiClient,
  opts: { provider_id?: string; label?: string; api_key?: string; base_url?: string } = {},
): Promise<Disposable<any>> {
  const cred = await api.createCredential({
    provider_id: opts.provider_id ?? 'openai',
    label: opts.label ?? `e2e cred ${unique()}`,
    api_key: opts.api_key ?? 'sk-e2e-fake-key',
    base_url: opts.base_url,
  })
  await confirmVisible(async () => {
    const list = (await api.listCredentials()) as Array<{ id: string }>
    if (!list.some((c) => c.id === cred.id)) throw new Error('credential not visible yet')
  })
  return { entity: cred, dispose: () => api.deleteCredential(cred.id).catch(() => {}) }
}

function unique(): string {
  // Math.random is unavailable in some sandboxes; use time + counter instead.
  _ctr += 1
  return `${Date.now().toString(36)}-${_ctr}`
}
let _ctr = 0
