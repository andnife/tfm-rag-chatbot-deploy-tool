// Typed wrapper over the backend API. Talks to BACKEND_URL directly (bypassing
// the UI) for fixture setup/teardown and for error paths the UI can't provoke.
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { BACKEND_URL } from './env'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string | undefined,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

type Json = Record<string, unknown>

export class ApiClient {
  token: string | undefined

  constructor(token?: string) {
    this.token = token
  }

  private async request(
    method: string,
    pathname: string,
    opts: { json?: unknown; form?: FormData; query?: Record<string, string | number> } = {},
  ): Promise<any> {
    const url = new URL(pathname, BACKEND_URL)
    for (const [k, v] of Object.entries(opts.query ?? {})) url.searchParams.set(k, String(v))
    const headers: Record<string, string> = {}
    if (this.token) headers.Authorization = `Bearer ${this.token}`
    let body: BodyInit | undefined
    if (opts.form) {
      body = opts.form
    } else if (opts.json !== undefined) {
      headers['Content-Type'] = 'application/json'
      body = JSON.stringify(opts.json)
    }
    const res = await fetch(url, { method, headers, body })
    const text = await res.text()
    const parsed = text ? safeJson(text) : undefined
    if (!res.ok) {
      const err = (parsed as Json | undefined)?.error as Json | undefined
      throw new ApiError(
        res.status,
        err?.code as string | undefined,
        (err?.message as string) ?? text ?? `HTTP ${res.status}`,
      )
    }
    return parsed
  }

  // ── Auth ───────────────────────────────────────────────────────────────
  async register(email: string, password: string) {
    const r = await this.request('POST', '/api/auth/register', { json: { email, password } })
    this.token = r.access_token
    return r
  }
  async login(email: string, password: string) {
    const r = await this.request('POST', '/api/auth/login', { json: { email, password } })
    this.token = r.access_token
    return r
  }
  me() {
    return this.request('GET', '/api/auth/me')
  }
  logout() {
    return this.request('POST', '/api/auth/logout')
  }

  // ── Providers / credentials ──────────────────────────────────────────────
  embeddingProviders() {
    return this.request('GET', '/api/providers/embedding')
  }
  llmProviders() {
    return this.request('GET', '/api/providers/llm')
  }
  listCredentials() {
    return this.request('GET', '/api/credentials')
  }
  createCredential(body: { provider_id: string; label: string; api_key: string; base_url?: string }) {
    return this.request('POST', '/api/credentials', { json: body })
  }
  testCredential(id: string, model_id: string) {
    return this.request('POST', `/api/credentials/${id}/test`, { json: { model_id } })
  }
  deleteCredential(id: string) {
    return this.request('DELETE', `/api/credentials/${id}`)
  }
  /** The synthetic Ollama credential auto-created at tenant bootstrap. */
  async ollamaCredentialId(): Promise<string> {
    const creds = (await this.listCredentials()) as Array<{ id: string; provider_id: string }>
    const c = creds.find((x) => x.provider_id === 'ollama')
    if (!c) throw new Error('no ollama credential for tenant — bootstrap skipped?')
    return c.id
  }

  // ── Knowledge bases / sources ─────────────────────────────────────────────
  listKBs() {
    return this.request('GET', '/api/knowledge-bases')
  }
  createKB(body: Json) {
    return this.request('POST', '/api/knowledge-bases', { json: body })
  }
  getKB(id: string) {
    return this.request('GET', `/api/knowledge-bases/${id}`)
  }
  updateKB(id: string, body: Json) {
    return this.request('PATCH', `/api/knowledge-bases/${id}`, { json: body })
  }
  deleteKB(id: string) {
    return this.request('DELETE', `/api/knowledge-bases/${id}`)
  }
  searchKB(id: string, body: Json) {
    return this.request('POST', `/api/knowledge-bases/${id}/search`, { json: body })
  }
  listSources(kbId: string) {
    return this.request('GET', `/api/knowledge-bases/${kbId}/sources`)
  }
  uploadDocument(kbId: string, filePath: string) {
    const form = new FormData()
    const buf = readFileSync(filePath)
    const name = path.basename(filePath)
    // The backend dispatches the loader strictly by mime (no extension
    // fallback), so set the part's Content-Type from the file extension.
    const MIME: Record<string, string> = {
      '.txt': 'text/plain',
      '.md': 'text/markdown',
      '.csv': 'text/csv',
      '.pdf': 'application/pdf',
      '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    }
    const mime = MIME[path.extname(name).toLowerCase()] ?? 'application/octet-stream'
    form.append('file', new Blob([buf], { type: mime }), name)
    return this.request('POST', `/api/knowledge-bases/${kbId}/sources/documents`, { form })
  }
  detachSource(kbId: string, sourceId: string) {
    return this.request('DELETE', `/api/knowledge-bases/${kbId}/sources/${sourceId}`)
  }
  reindexSource(kbId: string, sourceId: string) {
    return this.request('POST', `/api/knowledge-bases/${kbId}/sources/${sourceId}/reindex`)
  }
  testDbConnection(kbId: string, body: Json) {
    return this.request('POST', `/api/knowledge-bases/${kbId}/sources/test-connection`, { json: body })
  }
  attachDatabase(kbId: string, body: Json) {
    return this.request('POST', `/api/knowledge-bases/${kbId}/sources/databases`, { json: body })
  }
  getIngestionJob(jobId: string) {
    return this.request('GET', `/api/ingestion-jobs/${jobId}`)
  }
  /** Poll an ingestion job until done/failed or timeout (ms). */
  async waitIngestion(jobId: string, timeoutMs = 180_000): Promise<any> {
    const deadline = Date.now() + timeoutMs
    for (;;) {
      const job = await this.getIngestionJob(jobId)
      if (job.status === 'done' || job.status === 'failed') return job
      if (Date.now() > deadline) throw new Error(`ingestion ${jobId} timed out (last: ${job.status})`)
      await new Promise((r) => setTimeout(r, 2000))
    }
  }

  // ── Chatbots / chat / sessions ─────────────────────────────────────────────
  listChatbots() {
    return this.request('GET', '/api/chatbots')
  }
  createChatbot(body: Json) {
    return this.request('POST', '/api/chatbots', { json: body })
  }
  getChatbot(id: string) {
    return this.request('GET', `/api/chatbots/${id}`)
  }
  updateChatbot(id: string, body: Json) {
    return this.request('PATCH', `/api/chatbots/${id}`, { json: body })
  }
  deleteChatbot(id: string) {
    return this.request('DELETE', `/api/chatbots/${id}`)
  }
  welcomeSuggestions(id: string) {
    return this.request('POST', `/api/chatbots/${id}/welcome-suggestions`)
  }
  listSessions(chatbotId: string) {
    return this.request('GET', `/api/chatbots/${chatbotId}/sessions`)
  }
  chat(chatbotId: string, body: { message: string; session_id?: string }) {
    return this.request('POST', `/api/chatbots/${chatbotId}/chat`, { json: body })
  }
  getSession(sessionId: string) {
    return this.request('GET', `/api/sessions/${sessionId}`)
  }

  // ── Public widget ──────────────────────────────────────────────────────────
  publicConfig(publicKey: string) {
    return this.request('GET', `/api/public/chatbots/${publicKey}/config`)
  }
  publicChat(publicKey: string, body: Json) {
    return this.request('POST', `/api/public/chatbots/${publicKey}/chat`, { json: body })
  }

  // ── Evaluation ───────────────────────────────────────────────────────────
  // Entity-run flow (current): create a dataset (provisions its own KB),
  // import rows into it, then launch a run scoped to that dataset — the old
  // flat `POST /api/admin/eval/runs` (dataset_path-based) was dropped when
  // the judge became credential-first (see backend eval_runs.py history).
  listDatasets() {
    return this.request('GET', '/api/admin/eval/datasets')
  }
  getDataset(name: string) {
    return this.request('GET', `/api/admin/eval/datasets/${name}`)
  }
  createEvalDataset(body: Json) {
    return this.request('POST', '/api/admin/eval/datasets', { json: body })
  }
  importDatasetRows(datasetId: string, jsonl: string) {
    return this.request('POST', `/api/admin/eval/datasets/${datasetId}/rows/import`, { json: { jsonl } })
  }
  createEntityEvalRun(datasetId: string, body: Json) {
    return this.request('POST', `/api/admin/eval/datasets/${datasetId}/runs`, { json: body })
  }
  /** Deletes the dataset AND its provisioned KB atomically (see backend
   * manage_dataset.delete_eval_dataset) — prefer this over a plain
   * deleteKB() for entity datasets. */
  deleteEvalDataset(id: string) {
    return this.request('DELETE', `/api/admin/eval/datasets/${id}`)
  }
  getEvalRun(id: string) {
    return this.request('GET', `/api/admin/eval/runs/${id}`)
  }
  getEvalTrace(id: string) {
    return this.request('GET', `/api/admin/eval/runs/${id}/trace`)
  }
  listReports() {
    return this.request('GET', '/api/admin/eval/reports')
  }
  getReportJson(name: string) {
    return this.request('GET', `/api/admin/eval/reports/${name}/json`)
  }

  // ── Infra ─────────────────────────────────────────────────────────────────
  health() {
    return this.request('GET', '/health')
  }
  ollamaModels() {
    return this.request('GET', '/api/ollama/models')
  }
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    // FastAPI serializes Python float('nan')/inf as bare `NaN`/`Infinity`/
    // `-Infinity` (allow_nan defaults to on) — not valid JSON. A single such
    // token anywhere in the body would otherwise fail the whole parse (e.g.
    // one NaN metric in report.summary.metrics on a tiny eval run nuking the
    // entire report object). Retry once with those bare tokens replaced by
    // `null`, restricted to JSON value positions: preceded by `:`, `,`, or
    // `[` (plus optional whitespace — a `\b` anchor wouldn't work here, since
    // `-` is a non-word char and `\b` never matches between whitespace and
    // `-Infinity`) and followed by `,`, `}`, or `]`. Inside a quoted string
    // the neighbouring chars are ordinary text (or the string's `"` quotes),
    // so typical prose containing these words is left intact. Caveat: this is
    // a regex heuristic, not a real JSON tokenizer — a string whose CONTENT
    // mimics a value position (e.g. "a, NaN, b") would still be rewritten;
    // acceptable, since we only apply it after a strict parse already failed,
    // and the backend's real bodies are well-formed JSON plus bare NaN/inf.
    try {
      const sanitized = text.replace(/(?<=[:,[]\s*)-?(?:NaN|Infinity)(?=\s*[,\]}])/g, 'null')
      return JSON.parse(sanitized)
    } catch {
      return undefined
    }
  }
}
