# Mapa del dominio de inferencia (proveedores, credenciales, modelos, adaptadores)

> Para no perderse: cómo se relacionan proveedor / credencial / selección de modelo /
> adaptadores, y **por qué aparece `ChatOpenAI`** (que NO es lo mismo que nuestro
> proveedor `openai_compat`).

## Las 3 capas del dominio

### 1. Tipo de proveedor (catálogo estático) — *qué clase de proveedor es*
`domain/catalog/llm_providers.py` (`LLM_PROVIDER_CATALOG`) y `embedding_providers.py`.
Tres tipos: **`ollama`**, **`openai`**, **`openai_compat`**. Cada uno es un
`LLMProviderDescriptor` con metadatos de TIPO (no config de usuario):
- `config_source`: **`SERVER_ENV`** (ollama: sin key, url del servidor) o **`TENANT_CREDENTIAL`** (openai/openai_compat: key+url por tenant).
- `supports_tool_calling`, `requires_base_url_input`, `default_models` (orientativos).

### 2. Credencial (instancia configurada) — *cómo llegar a un proveedor concreto*
`ProviderCredentialRow` → `CredentialView`/`CredentialOut`.
Campos: `{ id, tenant_id, provider_id, label, base_url, api_key_encrypted, config_source, max_concurrency, min_request_interval_seconds }`.
Es **"un acceso configurado a un proveedor"**. Aquí vive el `provider_id` (y ahora los **rate limits**).

### 3. Referencia de modelo (selección) — *qué modelo usar y con qué credencial*
`ModelRef { credential_id, model_id }` (+ `EmbeddingRef { dim }`). Alias históricos:
`LLMSelection` / `EmbeddingSelection`. **NO** guarda `provider_id`/`base_url` (se derivan de la credencial).
Se almacena en:
- `chatbots.llm_selection` (por defecto) + `role_llm_selections` (evaluator/sql_generator/answer_generator).
- `knowledge_bases.embedding_selection` (+ `description_llm` opcional).
- `eval_runs.judge_credential_id` + `judge_model` (el juez).

### Resolución (el pegamento)
`resolve_inference_target(credential_id) -> (provider_id, base_url, api_key)` — carga la
credencial (tenant-scoped), descifra la key, valida SSRF. Punto ÚNICO de resolución.

## Los adaptadores — *cómo se LLAMA de verdad a inferencia* (aquí está el truco de `ChatOpenAI`)

Hay **DOS familias de clientes** que hablan con endpoints OpenAI-compatibles, según el uso:

| Uso | Cómo se llama | Cliente (objeto) | Fichero |
|---|---|---|---|
| **Generación** (chat: route/sql/grade/synthesize) + **listar modelos** | `LLMDispatcher.for_provider(provider_id)` | **nuestro** `OllamaLLMAdapter` / `OpenAILLMAdapter` | `infrastructure/llm_providers/` |
| **Embeddings** (retrieval + ingesta) | `EmbedderDispatcher.for_provider(provider_id)` | `OllamaEmbedder` / `OpenAIEmbedder` | `infrastructure/embedders/` |
| **Juez RAGAS** (scoring de la eval) | `RagasEvaluator._build_judge_llm()` | **LangChain** `OllamaLLM` **o** `ChatOpenAI` | `infrastructure/evaluation/ragas_evaluator.py` |
| **Embeddings internos de RAGAS** | dentro de RagasEvaluator | LangChain `OllamaEmbeddings` (bge-m3 local) | idem |

**Aclaración clave:** para una credencial `openai_compat`, la **generación** usa NUESTRO
`OpenAILLMAdapter`; el **juez** usa el `ChatOpenAI` de **LangChain** (porque RAGAS exige un
LLM envuelto en LangChain). Son dos clientes distintos que apuntan al MISMO endpoint
OpenAI-compatible. Por eso ves `ChatOpenAI`: es el cliente del **juez**, no nuestro proveedor.

## Rate limits (proactivo + reactivo)

**Proactivo** (config en la credencial, evita llegar al límite):
- `max_concurrency` → tope de peticiones en paralelo. En el juez se aplica como
  `RAGAS RunConfig.max_workers`.
- `min_request_interval_seconds` → espaciado mínimo entre peticiones (p. ej. 2.0 = 1 cada 2 s).
  En el juez `ChatOpenAI` se aplica con `InMemoryRateLimiter(requests_per_second = 1/intervalo)`
  de LangChain (`OllamaLLM` local no lo necesita).

**Reactivo** (resiliente si el límite se supera igualmente):
- Los endpoints OpenAI-compatibles devuelven **429 + `Retry-After`** estándar.
- El **SDK de openai** (dentro de `ChatOpenAI`) **reintenta 429 honrando `Retry-After`**
  automáticamente — provider-agnóstico. Fijamos `max_retries` alto para absorber ráfagas.
- RAGAS añade su propia capa de reintentos (`RunConfig.max_retries`/`max_wait`).

→ El proactivo suaviza (menos 429); el reactivo garantiza que, si aún así llega un 429,
se respeta el `Retry-After` y se reintenta en vez de perder la petición.

## Puntos de inferencia (resumen)
Chatbot: LLM por defecto + 3 roles (evaluator/sql_generator/answer_generator). KB: embedding
(+ description_llm opcional). Eval: juez (RAGAS) + embeddings RAGAS + juez-inline `gemma3:1b`
(local). Todos salvo los locales resuelven por credencial. Ver `EVAL-CAMPAIGN-WALKTHROUGH.md`.
