// @backend-source: backend/src/tfm_rag/infrastructure/api/schemas/*.py
// Tipos derivados a mano de los Pydantic models del backend.

// ============ Auth ============
export interface RegisterRequest { email: string; password: string }
export interface LoginRequest { email: string; password: string }
export interface AuthResponse {
  user_id: string
  tenant_id: string
  email: string
  access_token: string
  token_type?: string
}
export interface MeResponse { id: string; email: string; tenant_id: string; is_superadmin?: boolean }

// ============ Admin (superadmin cross-tenant overview) ============
export interface AdminUser { id: string; email: string; is_superadmin: boolean; created_at: string | null }
export interface AdminTenant { tenant_id: string; name: string; users: AdminUser[] }
export interface AdminTenantDetail {
  tenant_id: string
  chatbots: { id: string; name: string; description: string | null }[]
  knowledge_bases: { id: string; name: string; description: string | null }[]
  credentials: { id: string; provider_id: string; label: string; base_url: string | null; config_source: string }[]
}

// ============ Providers ============
export type ConfigSource = 'SERVER_ENV' | 'TENANT_CREDENTIAL'

export interface LlmProvider {
  id: string
  display_name: string
  description: string
  config_source: ConfigSource
  requires_base_url_input: boolean
  supports_tool_calling: boolean
  default_models: string[]
}

// Backend returns embedding default_models as tuples [model_id, dim].
export type EmbeddingModelTuple = [string, number]

export interface EmbeddingProvider {
  id: string
  display_name: string
  description: string
  config_source: ConfigSource
  requires_base_url_input: boolean
  default_models: EmbeddingModelTuple[]
}

// ============ Credentials ============
export interface CredentialIn { provider_id: string; label: string; api_key: string; base_url?: string | null; max_concurrency?: number | null; min_request_interval_seconds?: number | null }
export interface CredentialOut {
  id: string
  provider_id: string
  label: string
  base_url: string | null
  config_source: string
  max_concurrency: number | null
  min_request_interval_seconds: number | null
}
export interface TestCredentialIn { model_id: string }
export interface TestCredentialOut { ok: boolean; latency_ms: number | null; error: string | null }
export interface CredentialModel { id: string; kind: 'llm' | 'embedding' | 'unknown' }
export interface CredentialModelsResponse { models: CredentialModel[]; error: string | null }

// ============ Knowledge Bases ============
export interface ChunkingConfig {
  strategy: 'fixed' | 'recursive' | 'by_paragraph'
  chunk_size: number
  chunk_overlap: number
}
export interface EmbeddingSelection {
  credential_id: string
  model_id: string
  dim: number
}
export interface ModelRef {
  credential_id: string
  model_id: string
}
export interface KnowledgeBaseIn {
  name: string
  description?: string | null
  embedding_selection: EmbeddingSelection
  chunking_config: ChunkingConfig
  description_llm?: ModelRef | null
}
export interface KnowledgeBaseOut {
  id: string
  tenant_id: string
  name: string
  description: string | null
  embedding_selection: EmbeddingSelection
  chunking_config: ChunkingConfig
  description_llm?: ModelRef | null
}

export interface KnowledgeBaseDetailOut {
  kb: KnowledgeBaseOut
  sources: SourceOut[]
}

// ============ Sources ============
export type SourceType = 'document' | 'database'
export type IngestStatus = 'not_started' | 'queued' | 'running' | 'done' | 'failed'
export interface SourceOut {
  id: string
  kb_id: string
  type: SourceType
  ingest_status: IngestStatus
  filename: string | null
  error: string | null
  description: string | null
  last_ingest_at: string | null
}
export interface UploadDocumentOut {
  source_id: string
  job_id: string
}
export type IngestionStage = 'extracting' | 'chunking' | 'embedding' | 'indexing'
export interface IngestionJobOut {
  id: string
  source_id: string
  status: IngestStatus
  progress: number
  stage: IngestionStage | null
  items_done: number | null
  items_total: number | null
  error: string | null
  started_at: string
  finished_at: string | null
}
export interface SearchHit {
  point_id: string
  content: string
  source_id: string
  source_filename: string
  chunk_index: number
  score: number
  metadata: Record<string, unknown>
}

// ============ Chatbots ============
export interface LlmSelection {
  credential_id: string
  model_id: string
}
export interface GenerationConfig {
  temperature: number
  max_tokens: number
}
export interface PipelineConfig {
  top_k: number
  score_threshold: number
  max_self_correction_retries: number
  enable_reranker: boolean
  reranker_initial_top_k: number
  abstain_when_insufficient: boolean
  generation?: GenerationConfig
}
export type LlmRole = 'evaluator' | 'sql_generator' | 'answer_generator'
export interface RoleLlmSelections {
  evaluator?: LlmSelection
  sql_generator?: LlmSelection
  answer_generator?: LlmSelection
}
export interface WidgetConfig {
  theme: 'light' | 'dark'
  primary_color: string
  position: 'bottom-right' | 'bottom-left'
  title: string
  welcome_message: string
  welcome_message_named: string
  placeholder: string
  allowed_origins: string[]
}
export interface WelcomeSuggestions {
  welcome_message: string
  welcome_message_named: string
}
export interface ChatbotIn {
  name: string
  description?: string | null
  system_prompt: string
  llm_selection: LlmSelection
  role_llm_selections?: RoleLlmSelections
  kb_ids?: string[]
  pipeline_config?: PipelineConfig
  widget_config?: Partial<WidgetConfig>
}
export interface ChatbotOut {
  id: string
  tenant_id: string
  public_key: string
  name: string
  description: string | null
  system_prompt: string
  llm_selection: LlmSelection
  role_llm_selections: RoleLlmSelections
  pipeline_config: PipelineConfig
  widget_config: WidgetConfig
  kb_ids: string[]
}

// ============ Chat ============
export interface Citation {
  chunk_id: string
  source_id: string
  source_name: string
  location: string
  score: number
  preview?: string
}

// ============ Eval reports ============
export interface EvalReportSummary {
  name: string
  has_json: boolean
  has_markdown: boolean
}
export interface RoutingTraceView {
  route: string
  rationale: string
  attempts: Array<{
    index: number
    tool: string
    query: string | null
    num_chunks: number | null
    latency_ms: number
    sql: string | null
    row_count: number | null
    result_preview?: string | null
  }>
  verdicts: Array<{
    sufficient: boolean
    reformulated_query: string | null
    fixed_sql: string | null
    abstain_reason: string | null
  }>
}
export interface EvalReportJson {
  chatbot_name?: string
  ragas_judge_model?: string
  generator_model?: string | null
  dataset_path?: string
  scenario_filter?: string | null
  run_started_at?: string
  summary: {
    num_cases: number
    num_scored: number
    num_errors: number
    num_skipped?: number
    metrics: Record<string, number>
    metrics_std?: Record<string, number>
    per_scenario?: Record<
      string,
      {
        num_cases: number
        num_scored: number
        metrics: Record<string, number>
        metrics_std?: Record<string, number>
      }
    >
  }
  cases: Array<{
    question: string
    ground_truth: string
    scenario: string
    predicted_answer: string | null
    scores: Record<string, number> | null
    error: string | null
    retrieved_contexts: string[]
    iterations: Array<{
      tool: string
      latency_ms: number
      query?: string | null
      num_chunks?: number | null
      sql?: string | null
      row_count?: number | null
      result_preview?: string | null
    }>
    routing_trace?: RoutingTraceView
  }>
}
export interface RetrievalIteration {
  index: number
  tool: string
  query: string | null
  num_chunks: number | null
  latency_ms: number
}
export interface ChatRequest {
  message: string
  session_id?: string | null
}
export interface ChatResponse {
  session_id: string
  message_id: string
  content: string
  citations: Citation[]
  iterations: RetrievalIteration[]
}

// ============ Errors ============
export interface ApiErrorBody {
  code?: string
  message?: string
  detail?: unknown
}

// ============ Ollama ============
export interface OllamaModel {
  name: string
  size: number
  digest: string
  modified_at: string
  details: Record<string, unknown>
}
export interface OllamaModelsResponse {
  models: OllamaModel[]
}

// ============ Knowledge Base Update ============
export interface UpdateKbOut {
  kb: KnowledgeBaseOut
  reindex_required: boolean
}
export interface ReindexAllOut {
  source_count: number
}

// ============ Database Sources ============
export type DatabaseDriver = 'postgres' | 'mysql'
export type SslMode = 'disable' | 'require'
export interface DatabaseSourceTestConnectionIn {
  type: SourceType
  spec: Record<string, unknown>
}
export interface DatabaseTestConnectionOut {
  ok: boolean
  error: string | null
  details: unknown
}
export interface DatabaseSourceAttachIn {
  driver: DatabaseDriver
  host: string
  port: number
  db_name: string
  username: string
  password: string
  ssl_mode?: SslMode
}
export interface DatabaseAttachOut {
  source_id: string
  snapshot_tables: number
  snapshot_captured_at: string
}

// ============ Eval runs ============
export interface EvalRun {
  id: string
  chatbot_id: string
  dataset_path: string | null
  scenario_filter: string | null
  judge_credential_id: string | null
  judge_model: string
  generator_model?: string | null
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  progress: number
  report_dir: string | null
  error: string | null
  created_at: string | null
  started_at: string | null
  finished_at: string | null
  // Token count telemetry — nullable so legacy runs tab consumers are unaffected
  tokens_gen_in: number | null
  tokens_gen_out: number | null
  tokens_judge_in: number | null
  tokens_judge_out: number | null
  dataset_id?: string | null
  chatbot_name?: string | null
  dataset_name?: string | null
}

export interface EvalRunLive {
  index?: number
  total?: number
  question?: string
  current_step?: string
  steps?: { step: string; detail: string; elapsed_ms: number }[]
  started_at?: string | null
  // Scoring phase (written during RAGAS scoring; absent during generation)
  phase?: 'scoring'
  scoring_done?: number
  scoring_total?: number
  elapsed_seconds?: number
  eta_seconds?: number | null
}

export interface EvalRunTraceIteration {
  index: number
  tool: string
  query: string | null
  num_chunks: number | null
  latency_ms: number
  sql: string | null
  row_count: number | null
}

export interface EvalRunTraceRow {
  idx: number
  total: number
  question: string
  scenario: string | null
  ground_truth: string | null
  predicted_answer: string | null
  iterations: EvalRunTraceIteration[]
  citations: Citation[]
  retrieved_contexts: string[]
  judged_correct: boolean | null
  judge_reason: string
  error: string | null
  // Task-1 backend additions — optional so legacy trace consumers are unaffected
  prompt_tokens?: number | null
  completion_tokens?: number | null
  cumulative_prompt_tokens?: number | null
  cumulative_completion_tokens?: number | null
  eta_seconds?: number | null
}

// ============ Entity-run / calibration types ============
export interface EntityRunIn {
  chatbot_id: string
  judge_credential_id: string
  judge_model: string
}

export interface CalibrateIn extends EntityRunIn {
  sample_size?: number
}

export interface CalibrateResult {
  sample_size: number
  avg_gen_tokens: number
  avg_judge_tokens: number
  avg_seconds: number
  projected_total: {
    tokens: number
    seconds: number
  }
}

// ============ Sessions ============
export interface SessionSummary {
  id: string
  chatbot_id: string
  origin: string
  created_at: string
  last_activity_at: string
}
export interface SessionMessage {
  id: string
  session_id: string
  role: string
  content: string
  citations: Record<string, unknown>[]
  metadata: Record<string, unknown>
  created_at: string
}
export interface SessionDetail {
  session: SessionSummary
  messages: SessionMessage[]
}

// ============ Eval Datasets (managed dataset entity) ============
export type DatasetStatus = 'draft' | 'processing' | 'ready' | 'failed'

export interface Dataset {
  id: string
  name: string
  description: string | null
  knowledge_base_id: string | null
  db_schema_name: string | null
  status: DatasetStatus
  status_error: string | null
  num_rows: number
}

export interface DatasetRow {
  ordinal: number
  question: string
  ground_truth: string
  scenario: 'doc_only' | 'sql_only' | 'mixed' | 'abstain'
  complexity: 'factual' | 'inferencial' | 'comparativa'
  reference_contexts: string[] | null
  sql_reference: string | null
  source_doc: string | null
}

export interface CreateDatasetIn {
  name: string
  description?: string | null
  embedding_selection: EmbeddingSelection
  chunking_config?: ChunkingConfig | null
}

export interface RowInput {
  question: string
  ground_truth: string
  scenario: string
  complexity: string
  reference_contexts?: string[]
  sql_reference?: string | null
  source_doc?: string | null
}

