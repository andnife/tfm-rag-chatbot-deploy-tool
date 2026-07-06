import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, apiJson } from './api'
import { uploadDocumentXhr } from './uploadXhr'
import type {
  AuthResponse, ChatRequest, ChatResponse, ChatbotIn, ChatbotOut,
  CredentialIn, CredentialModelsResponse, CredentialOut, DatabaseAttachOut, DatabaseSourceAttachIn,
  DatabaseSourceTestConnectionIn, DatabaseTestConnectionOut, EmbeddingProvider,
  IngestionJobOut, KnowledgeBaseDetailOut, KnowledgeBaseIn, KnowledgeBaseOut, LlmProvider, LoginRequest,
  MeResponse, OllamaModelsResponse, RegisterRequest, ReindexAllOut,
  EvalReportJson,
  EvalRun, EvalRunLive, EvalRunTraceRow,
  SearchHit, SessionDetail, SessionSummary, SourceOut, TestCredentialIn, UploadDocumentOut,
  TestCredentialOut, UpdateKbOut, WelcomeSuggestions,
  Dataset, DatasetRow, CreateDatasetIn,
  EntityRunIn, CalibrateIn, CalibrateResult,
  AdminTenant, AdminTenantDetail,
} from '@/types/api'

// ============ Keys factory ============
export const qk = {
  me: ['auth', 'me'] as const,
  providers: {
    llm: ['providers', 'llm'] as const,
    embedding: ['providers', 'embedding'] as const,
  },
  credentials: {
    all: ['credentials'] as const,
  },
  kbs: {
    all: ['kb'] as const,
    one: (id: string) => ['kb', id] as const,
    sources: (id: string) => ['kb', id, 'sources'] as const,
  },
  chatbots: {
    all: ['chatbot'] as const,
    sessions: (id: string) => ['chatbot', id, 'sessions'] as const,
    one: (id: string) => ['chatbot', id] as const,
  },
  ingestionJob: (id: string) => ['ingestion-job', id] as const,
  evalReports: {
    json: (name: string) => ['eval', 'reports', name, 'json'] as const,
    markdown: (name: string) => ['eval', 'reports', name, 'markdown'] as const,
  },
}

// ============ Auth ============
export function useLogin() {
  return useMutation({
    mutationFn: (req: LoginRequest) => apiJson<AuthResponse>('/auth/login', 'POST', req),
  })
}
export function useRegister() {
  return useMutation({
    mutationFn: (req: RegisterRequest) => apiJson<AuthResponse>('/auth/register', 'POST', req),
  })
}
export function useMe() {
  return useQuery({
    queryKey: qk.me,
    queryFn: () => apiFetch<MeResponse>('/auth/me'),
    retry: false,
  })
}

// ============ Admin (superadmin cross-tenant overview) ============
export function useAdminTenants() {
  return useQuery({
    queryKey: ['admin', 'tenants'] as const,
    queryFn: () => apiFetch<AdminTenant[]>('/admin/overview/tenants'),
  })
}
export function useAdminTenantDetail(tenantId: string | null) {
  return useQuery({
    queryKey: ['admin', 'tenant', tenantId] as const,
    queryFn: () => apiFetch<AdminTenantDetail>(`/admin/overview/tenants/${tenantId}`),
    enabled: !!tenantId,
  })
}

// ============ Providers ============
export function useLlmProviders() {
  return useQuery({
    queryKey: qk.providers.llm,
    queryFn: () => apiFetch<LlmProvider[]>('/providers/llm'),
    staleTime: 5 * 60_000,
  })
}
export function useEmbeddingProviders() {
  return useQuery({
    queryKey: qk.providers.embedding,
    queryFn: () => apiFetch<EmbeddingProvider[]>('/providers/embedding'),
    staleTime: 5 * 60_000,
  })
}

// ============ Credentials ============
export function useCredentials() {
  return useQuery({
    queryKey: qk.credentials.all,
    queryFn: () => apiFetch<CredentialOut[]>('/credentials'),
  })
}
export function useCreateCredential() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: CredentialIn) => apiJson<CredentialOut>('/credentials', 'POST', input),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.credentials.all }),
  })
}
export function useDeleteCredential() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiJson<void>(`/credentials/${id}`, 'DELETE'),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.credentials.all }),
  })
}
export function useTestCredential() {
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: TestCredentialIn }) =>
      apiJson<TestCredentialOut>(`/credentials/${id}/test`, 'POST', input),
  })
}

// ============ Knowledge Bases ============
export function useKnowledgeBases() {
  return useQuery({
    queryKey: qk.kbs.all,
    queryFn: () => apiFetch<KnowledgeBaseOut[]>('/knowledge-bases'),
  })
}
export function useKnowledgeBase(id: string) {
  return useQuery({
    queryKey: qk.kbs.one(id),
    queryFn: async () => {
      const detail = await apiFetch<KnowledgeBaseDetailOut>(`/knowledge-bases/${id}`)
      return detail.kb
    },
    enabled: !!id,
  })
}
export function useKbSources(id: string) {
  return useQuery({
    queryKey: qk.kbs.sources(id),
    queryFn: () => apiFetch<SourceOut[]>(`/knowledge-bases/${id}/sources`),
    enabled: !!id,
  })
}
export function useCreateKnowledgeBase() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: KnowledgeBaseIn) => apiJson<KnowledgeBaseOut>('/knowledge-bases', 'POST', input),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.kbs.all }),
  })
}
export function useUploadDocument(kbId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ file, onProgress }: { file: File; onProgress?: (f: number) => void }) =>
      uploadDocumentXhr(kbId, file, onProgress ?? (() => {})),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.kbs.sources(kbId) }),
  })
}
export function useReindexSource(kbId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (sourceId: string) =>
      apiJson<UploadDocumentOut>(
        `/knowledge-bases/${kbId}/sources/${sourceId}/reindex`,
        'POST',
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.kbs.sources(kbId) })
      qc.invalidateQueries({ queryKey: qk.kbs.one(kbId) })
    },
  })
}
export function useDeleteSource(kbId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (sourceId: string) =>
      apiJson<void>(`/knowledge-bases/${kbId}/sources/${sourceId}`, 'DELETE'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.kbs.sources(kbId) })
      qc.invalidateQueries({ queryKey: qk.kbs.one(kbId) })
    },
  })
}
export function useKbSearch(kbId: string) {
  return useMutation({
    mutationFn: (query: string) =>
      apiJson<SearchHit[]>(`/knowledge-bases/${kbId}/search`, 'POST', { query, top_k: 5 }),
  })
}
export function useIngestionJob(jobId: string | null) {
  return useQuery({
    queryKey: jobId ? qk.ingestionJob(jobId) : ['ingestion-job', 'noop'],
    queryFn: () => apiFetch<IngestionJobOut>(`/ingestion-jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const status = q.state.data?.status
      // Keep polling while the job is in any non-terminal state. A job is
      // created as 'queued' by the backend, so polling MUST cover it or the
      // upload dialog freezes before ever reaching 'done'.
      return status === 'queued' || status === 'running' || status === 'not_started'
        ? 2000
        : false
    },
  })
}
export function useOllamaModels() {
  return useQuery({
    queryKey: ['ollama-models'] as const,
    queryFn: () => apiFetch<OllamaModelsResponse>('/ollama/models'),
    staleTime: 30_000,
  })
}
export function useModelsForCredential(credentialId: string | null) {
  return useQuery({
    queryKey: ['credential-models', credentialId],
    queryFn: () => apiFetch<CredentialModelsResponse>(`/credentials/${credentialId}/models`),
    enabled: !!credentialId,
    staleTime: 30_000,
  })
}

export interface EmbeddingDimensionResponse { dim: number | null; error: string | null }

// Auto-detect an embedding model's dimension by probing the endpoint (the
// backend embeds a short text and measures the vector length). Only runs when
// enabled (i.e. the dimension isn't already known from the catalog).
export function useEmbeddingDimension(
  credentialId: string | null,
  model: string,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ['embedding-dim', credentialId, model],
    queryFn: () => apiFetch<EmbeddingDimensionResponse>(
      `/credentials/${credentialId}/embedding-dimension?model=${encodeURIComponent(model)}`,
    ),
    enabled: enabled && !!credentialId && !!model,
    staleTime: 300_000,
    retry: false,
  })
}
export function useUpdateKnowledgeBase(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: Partial<KnowledgeBaseIn>) =>
      apiJson<UpdateKbOut>(`/knowledge-bases/${id}`, 'PATCH', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.kbs.all })
      qc.invalidateQueries({ queryKey: qk.kbs.one(id) })
    },
  })
}
export function useDeleteKnowledgeBase() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiJson<void>(`/knowledge-bases/${id}`, 'DELETE'),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.kbs.all }),
  })
}
export function useTestDatabaseConnection(kbId: string) {
  return useMutation({
    mutationFn: (input: DatabaseSourceTestConnectionIn) =>
      apiJson<DatabaseTestConnectionOut>(`/knowledge-bases/${kbId}/sources/test-connection`, 'POST', input),
  })
}
export function useAttachDatabaseSource(kbId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: DatabaseSourceAttachIn) =>
      apiJson<DatabaseAttachOut>(`/knowledge-bases/${kbId}/sources/databases`, 'POST', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.kbs.sources(kbId) })
      qc.invalidateQueries({ queryKey: qk.kbs.all })
    },
  })
}
export function useReindexAll(kbId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const sources = await apiFetch<SourceOut[]>(`/knowledge-bases/${kbId}/sources`)
      const docSources = sources.filter(s => s.type === 'document')
      for (const src of docSources) {
        await apiFetch(`/knowledge-bases/${kbId}/sources/${src.id}/reindex`, { method: 'POST' })
      }
      return { source_count: docSources.length } as ReindexAllOut
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.kbs.sources(kbId) })
    },
  })
}

// ============ Chatbots ============
export function useChatbots() {
  return useQuery({
    queryKey: qk.chatbots.all,
    queryFn: () => apiFetch<ChatbotOut[]>('/chatbots'),
  })
}
export function useChatbot(id: string) {
  return useQuery({
    queryKey: qk.chatbots.one(id),
    queryFn: () => apiFetch<ChatbotOut>(`/chatbots/${id}`),
    enabled: !!id,
  })
}
export function useCreateChatbot() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: ChatbotIn) => apiJson<ChatbotOut>('/chatbots', 'POST', input),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.chatbots.all }),
  })
}
export function useUpdateChatbot(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: Partial<ChatbotIn>) => apiJson<ChatbotOut>(`/chatbots/${id}`, 'PATCH', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.chatbots.all })
      qc.invalidateQueries({ queryKey: qk.chatbots.one(id) })
    },
  })
}
export function useDeleteChatbot() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiJson<void>(`/chatbots/${id}`, 'DELETE'),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.chatbots.all }),
  })
}
export function useWelcomeSuggestions(id: string) {
  return useMutation({
    mutationFn: () =>
      apiJson<WelcomeSuggestions>(`/chatbots/${id}/welcome-suggestions`, 'POST'),
  })
}
export function useChat(chatbotId: string) {
  return useMutation({
    mutationFn: (req: ChatRequest) =>
      apiJson<ChatResponse>(`/chatbots/${chatbotId}/chat`, 'POST', req),
  })
}

// ============ Sessions ============
export function useChatbotSessions(chatbotId: string) {
  return useQuery({
    queryKey: qk.chatbots.sessions(chatbotId),
    queryFn: () => apiFetch<SessionSummary[]>(`/chatbots/${chatbotId}/sessions`),
    enabled: !!chatbotId,
  })
}
export function useSessionDetail(sessionId: string | null) {
  return useQuery({
    queryKey: ['session-detail', sessionId] as const,
    queryFn: () => apiFetch<SessionDetail>(`/sessions/${sessionId}`),
    enabled: !!sessionId,
  })
}

// ============ Eval reports ============
export function useEvalReportJson(name: string | null) {
  return useQuery({
    queryKey: name ? qk.evalReports.json(name) : ['eval', 'noop'],
    queryFn: () => apiFetch<EvalReportJson>(`/admin/eval/reports/${name}/json`),
    enabled: !!name,
  })
}
export function useEvalReportMarkdown(name: string | null) {
  return useQuery({
    queryKey: name ? qk.evalReports.markdown(name) : ['eval', 'noop'],
    queryFn: () =>
      apiFetch<{ content: string }>(`/admin/eval/reports/${name}/markdown`),
    enabled: !!name,
  })
}

// ============ Dataset lifecycle (managed dataset entity) ============
export function useDatasetList() {
  return useQuery({ queryKey: ['datasets'], queryFn: () => apiFetch<Dataset[]>('/admin/eval/datasets') });
}
export function useDataset(id: string | null) {
  return useQuery({
    queryKey: ['datasets', id],
    queryFn: () => apiFetch<Dataset>(`/admin/eval/datasets/${id}`),
    enabled: !!id,
  });
}
export function useCreateDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateDatasetIn) => apiJson<Dataset>('/admin/eval/datasets', 'POST', input),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['datasets'] }),
  });
}
export function useDeleteDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/admin/eval/datasets/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['datasets'] }),
  });
}
export function useDatasetRows(id: string | null) {
  return useQuery({
    queryKey: ['datasets', id, 'rows'],
    queryFn: () => apiFetch<DatasetRow[]>(`/admin/eval/datasets/${id}/rows`),
    enabled: !!id,
  });
}
export function useImportDatasetRows(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jsonl: string) => apiJson<Dataset>(`/admin/eval/datasets/${id}/rows/import`, 'POST', { jsonl }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['datasets', id] }),
  });
}
export function useSetDatasetSeed(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sql: string) => apiJson<Dataset>(`/admin/eval/datasets/${id}/sql-seed`, 'POST', { sql }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['datasets', id] }),
  });
}
export function useProcessDataset(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiJson<Dataset>(`/admin/eval/datasets/${id}/process`, 'POST'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['datasets', id] }),
  });
}
// ============ Eval datasets + runs ============
export function useEvalRuns() {
  return useQuery({
    queryKey: ['evalRuns'],
    queryFn: () => apiFetch<EvalRun[]>('/admin/eval/runs'),
    refetchInterval: (query) => {
      const data = query.state.data as EvalRun[] | undefined
      return data?.some((r) => r.status === 'queued' || r.status === 'running')
        ? 2000
        : false
      // cancelled / done / failed are terminal — no polling needed
    },
  })
}

export function useEvalRunTrace(runId: string | null, active: boolean) {
  return useQuery({
    queryKey: ['evalRunTrace', runId],
    queryFn: () => apiFetch<EvalRunTraceRow[]>(`/admin/eval/runs/${runId}/trace`),
    enabled: active && !!runId,
    refetchInterval: active ? 2000 : false,
  })
}

// ============ Entity runs + calibration ============
export function useCreateEntityRun(datasetId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: EntityRunIn) =>
      apiJson<EvalRun>(`/admin/eval/datasets/${datasetId}/runs`, 'POST', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['evalRuns'] }),
  })
}

export function useCalibrate(datasetId: string) {
  return useMutation({
    mutationFn: (body: CalibrateIn) =>
      apiJson<CalibrateResult>(`/admin/eval/datasets/${datasetId}/calibrate`, 'POST', body),
  })
}

export function useEvalRun(runId: string | null, active: boolean) {
  return useQuery({
    queryKey: ['evalRun', runId],
    queryFn: () => apiFetch<EvalRun>(`/admin/eval/runs/${runId}`),
    enabled: !!runId,
    refetchInterval: active ? 2000 : false,
  })
}

export function useEvalRunLive(runId: string | null, active: boolean) {
  return useQuery({
    queryKey: ['eval-run-live', runId],
    queryFn: () => apiFetch<EvalRunLive>(`/admin/eval/runs/${runId}/live`),
    enabled: !!runId,
    refetchInterval: active ? 2000 : false,
  })
}

export function useCancelRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (runId: string) => apiFetch(`/admin/eval/runs/${runId}/cancel`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['evalRuns'] }),
  })
}
