# Handover — sesión de brainstorming TFM RAG Platform

**Última actualización:** 2026-05-24, sesión 7 (**M3 CERRADO** — plan #15 implementado completo. 138 unit + 28 integration tests passing. La demo agéntica funciona end-to-end contra Ollama llama3.1 vivo: ingest doc → chat → respuesta con citas reales a la fuente. 12/17 plans done).
**Continuación:** plans M4–M7 ortogonales a la demo principal. Sugerencia de orden: #11 (CHATBOT-WIDGET-CONFIG) o #16 (WIDGET-RUNTIME) si se quiere demo pública; #9 + #13 (KB-DB-SOURCES + CHAT-SQL-EXECUTION) si se quiere extender capacidad RAG; #17 (EVAL-RAGAS) si toca evaluación.

Este documento es el punto de entrada para retomar el trabajo. Si lo estás leyendo en una sesión nueva: empieza aquí, no por el `.log`.

---

## 1. Qué estamos haciendo

Producir un **documento HTML autocontenido** que sirve como **spec ejecutable** para que agentes implementen el MVP de la plataforma RAG descrita en `docs/TFM - Segunda entrega - Ade Cabo Cuartero.pdf`. El HTML también será la fuente desde la que se extraerán **OpenSpec proposals** (cada capability → 1 proposal).

El HTML aún no se ha escrito. Estamos en fase de **brainstorming/diseño por secciones**: cada sección se presenta, se discute, se ajusta y se cierra antes de pasar a la siguiente. Cuando estén las 15 cerradas, se escribe el HTML y luego se invoca la skill `writing-plans` para el plan de implementación.

**Skill activa:** `superpowers:brainstorming`. El terminal state de esta skill es `writing-plans` (NO se invoca ninguna otra skill de implementación desde aquí — frontend-design, mcp-builder, etc., son ilegales en este punto).

---

## 2. Dónde están los artefactos

- **Memoria del TFM** (input principal): `docs/TFM - Segunda entrega - Ade Cabo Cuartero.pdf`
- **Log completo de la conversación**: `conversation-2026-05-19.log` (raíz del repo)
- **Code samples literales de la sesión 1**: `code-samples-2026-05-19.md` (raíz del repo). **Atención**: snapshot de la sesión 1; §6 introdujo cambios que afectan parte del código (rename `KnowledgeSource → KnowledgeBase + Source` polimórfico). Cuando vuelvas a generar código, usa el log como fuente canónica.
- **Este handover**: `handover.md` (raíz del repo)
- **HTML final** (cuando se escriba): `docs/superpowers/specs/2026-05-19-tfm-roadmap-funcional-design.html`

Memoria global guardada en `~/.claude/projects/-home-acabo-personal-tfmragapp/memory/` con la preferencia "actualiza el .log periódicamente sin que te lo pida". Respétala.

---

## 3. Estado de las 15 secciones del documento

| # | Sección | Estado |
|---|---|---|
| 1 | Visión, glosario y supuestos | ✅ Aprobada |
| 2 | Mapa de módulos y dependencias | ✅ Aprobada (rectificar al escribir HTML — ver §5 de este handover) |
| 3 | Flujos end-to-end (A–G) | ✅ Aprobada (rectificar — pasa a A–H con loop agéntico) |
| 4 | Dominio: entidades, value objects, contratos Python, errores | ✅ Cerrada (rectificar — KnowledgeBase + Source polimórfico) |
| 5 | Adaptadores MVP | ✅ Cerrada (rectificar — añadir Reranker; quitar Dropbox) |
| 6 | Casos de uso / servicios de aplicación | ✅ **Cerrada** (con cambios fuertes; ver bloque dedicado abajo) |
| 7 | Catálogo de capabilities (CAP-*) — fuente para OpenSpec | ✅ Cerrada (17 CAPs con fichas) |
| 8 | API REST (endpoints, req/resp) | ✅ Cerrada |
| 9 | Modelo de datos (Postgres + Qdrant) | ✅ Cerrada |
| 10 | Panel (sitemap + wireframes) | ✅ Cerrada |
| 11 | Widget embebible | ✅ Cerrada |
| 12 | Seguridad y multi-tenancy | ✅ Cerrada |
| 13 | Evaluación (RAGAS) | ✅ Cerrada |
| 14 | Roadmap M1–M7 | ✅ Cerrada |
| 15 | Riesgos y mitigaciones | ✅ Cerrada |

Las secciones 2-5 quedan **aprobadas con rectificaciones pendientes**. Las rectificaciones no se re-litigan; se aplican directamente al redactar el HTML. Están detalladas en §5 de este handover.

---

## 4. Resumen de §6 — pivots y modelo final (memorizar)

§6 tuvo cuatro pivots durante la sesión 2. El estado de salida es:

**Separación módulo LLM ↔ módulo RAG.** Las fuentes de conocimiento salen del chatbot y viven a nivel tenant. El chatbot **referencia** KBs, no las contiene.

**KnowledgeBase como contenedor polimórfico.** Una KB agrupa:
- N `DocumentSource` (archivos subidos o carpetas cloud sincronizadas)
- N `DatabaseSource` (conexiones SQL read-only)

`Source` es entidad polimórfica del dominio. Su "consultarse" vive en puertos + use cases, no en métodos de la entidad.

**Wizard del chatbot** = cliente puro + un único `POST /api/chatbots` al final. Sin estado `draft` en BD. Sin `UpdateChatbotStep` parametrizado.

**RAG agéntico.** `AnswerQuery` es un **agent loop** con el LLM eligiendo entre las tools `search_docs`, `query_database`, `final_answer`, `abstain` en cada iteración. Hasta `max_retrieval_iterations` (default 3, configurable 1-5, UX: "Profundidad de exploración"). Si tras N iteraciones no hay contexto suficiente, el LLM admite que no puede responder.

**Reparto de configuración:**

| En KnowledgeBase (config de **indexación**) | En Chatbot (config de **consulta**) |
|---|---|
| `chunking_config` | `llm_selection` + `system_prompt` + `generation_config` |
| `embedding_selection` | `top_k`, `score_threshold` |
| | `router_llm_selection` (modelo barato para decisiones) |
| | `max_retrieval_iterations` (1-5, default 3) |
| | `agentic_mode` (bool, default true) |
| | `enable_reranker` (bool, default false) |
| | `reranker_initial_top_k` (default 30) |
| | `abstain_when_insufficient` (bool, default true) |
| | `widget_config` |

**Validación dura:** todas las KBs adjuntas a un chatbot deben tener el mismo `embedding_selection`. Si no → `IncompatibleEmbeddingsError`. UI filtra opciones.

**Nuevo puerto:** `Reranker` (adapters: `BGECrossEncoderReranker` local, `CohereRerankerAdapter` opcional).

**Nuevo VO:** `RetrievalIteration` (telemetría por turno; se persiste en `ChatMessage.metadata.iterations[]`).

---

## 5. Rectificaciones pendientes a §2, §3, §4, §5 (aplicar al escribir HTML)

**§2 Mapa de módulos:**
- `application/sources/` → `application/knowledge/`
- `adapters/rerankers/` nuevo subpackage
- Frontend: `/knowledge` como top-level del panel (junto a `/chatbots` y `/settings`)

**§3 Flujos:**
- Flujo B (chat documental) y C (chat docs+SQL): reescribir con agent loop, no pipeline lineal
- Flujo F (ingesta cloud): ahora pertenece a una KB, no a un chatbot
- Flujo G (introspección SQL): idem
- **Nuevo Flujo H**: ciclo agéntico de retrieval (diagrama de secuencia del loop)

**§4 Dominio:**
- Renombrar `KnowledgeSource` → `KnowledgeBase` + introducir `Source` polimórfico (`DocumentSource`, `DatabaseSource`)
- `Chatbot` pierde campos de fuentes, gana N:M con KBs
- `PipelineConfig` gana: `max_retrieval_iterations`, `agentic_mode`, `enable_reranker`, `reranker_initial_top_k`, `abstain_when_insufficient`, `router_llm_selection`
- Añadir VO `RetrievalIteration`
- Añadir errores en `domain/errors/knowledge.py`: `KnowledgeBaseNotFoundError`, `KnowledgeBaseInUseError`, `IncompatibleEmbeddingsError`, `SourceNotFoundError`, `UnsupportedDocumentTypeError`, `SchemaIntrospectionError`

**§5 Adapters:**
- Añadir `adapters/rerankers/` (BGE local + Cohere opcional)
- `sql_sources`: postgres + mysql (Q5.3 confirmada)
- `cloud_storage`: gdrive + s3 (sin dropbox, Q5.2)
- `document_loaders`: pdf, docx, txt, csv, md, **xlsx** (Q5.1)

---

## 6. Decisiones ya tomadas (no re-litigar)

| Eje | Decisión |
|---|---|
| Tipo de documento | Funcional detallado + roadmap M1-Mn en HTML autocontenido con nav lateral |
| Audiencia del HTML | Ade (visualizar) + agentes (implementar). **Spec ejecutable, no documento estético.** |
| Origen para OpenSpec | Sección 7 — catálogo de capabilities con IDs `CAP-*` |
| Tenancy | Multi-tenant real. 1 admin = 1 tenant en MVP (sin invitaciones) |
| Auth | Email+password + Google OAuth opcional |
| Contratos de puertos | Firmas Python completas (ABC, tipos, errores) |
| Catálogo de proveedores | Vive **en código** (`domain/catalog/llm_providers.py`). No hay superadmin. |
| Tipos de credencial | `SERVER_ENV` (Ollama) o `TENANT_CREDENTIAL` (OpenAI, OpenAI-compat) |
| Widget | Configurador en panel + preview en vivo + snippet copiable |
| Config pipeline | Modo Simple (preset) y Avanzado (chunking, top-k, threshold, reranker, agentic) |
| Upload de archivos | Drag&drop **en /knowledge** + conectores cloud |
| Async ingesta | FastAPI BackgroundTasks + tabla `ingestion_jobs` + polling |
| Conversación | Multi-turno con `session_id` persistido en BD |
| Repo layout | `backend/` + `frontend/` + `widget/` + `infra/` + `scripts/` |
| System prompt | Textarea libre + plantillas opcionales |
| Router (chat) | **LLM con function calling en loop** (1-5 iteraciones). Tools: `search_docs`, `query_database`, `final_answer`, `abstain` |
| `router_llm_selection` | Opcional por chatbot; usa modelo más barato para decisiones del loop |
| API keys | Por tenant. Cifradas con Fernet |
| Sesión JWT | Corta (1h). Sin revocación en BD en MVP |
| Granularidad roadmap | Hitos end-to-end M1-Mn demo-ables |
| **KBs** | Entidad a nivel tenant. N:M con chatbots. Contiene N DocumentSource + N DatabaseSource |
| **Embeddings cross-KB** | Todas las KBs adjuntas a un chatbot deben usar el mismo embedding_selection |
| **Indexación** | Una sola vez por documento dentro de su KB |
| **Reranker** | Puerto en MVP. Opt-in por chatbot (default off) |

---

## 7. Nomenclatura clave (memorizar antes de retomar)

```
# Proveedores de modelos:
LLMProvider                # Puerto (ABC)
OllamaLLMAdapter           # Adapter concreto
OpenAILLMAdapter           # Adapter concreto
OpenAICompatLLMAdapter     # Adapter concreto genérico (Groq, Together, ...)
LLMProviderDescriptor      # Metadata en el catálogo
LLM_PROVIDER_CATALOG       # dict {provider_id: (Descriptor, adapter_class)}
ProviderCredential         # BD, por tenant (api_key cifrada, base_url opcional)
LLMSelection               # VO dentro de Chatbot: {provider_id, credential_id, model_id}
EmbeddingSelection         # VO dentro de KnowledgeBase

# Conocimiento (nuevo modelo §6):
KnowledgeBase              # Contenedor a nivel tenant
Source                     # Entidad base polimórfica
DocumentSource             # Subtipo: archivos (chunked + embedded)
DatabaseSource             # Subtipo: conexión SQL (introspect + text2SQL)
chatbot_knowledge_base     # Tabla N:M Chatbot ↔ KnowledgeBase

# Loop agéntico (nuevo §6):
Reranker                   # Puerto nuevo (cross-encoder reordena top-N → top-K)
RetrievalIteration         # VO de telemetría por iteración del loop
ToolCall                   # Decisión del Router en cada turno
```

Análogo para `EmbeddingProvider`, `CloudStorageConnector`, `SQLDataSource`.

`Tenant` es el espacio aislado. En MVP es 1:1 con `User` (invisible en UI) pero existe en el modelo para aislamiento real (filtros BD, colecciones Qdrant físicas, storage prefix).

---

## 7-bis. Estado de la Sección 7 (en curso)

Sesión 3 (2026-05-19) cerró las 3 decisiones de enfoque (Q7.1–Q7.3). Sesión 4 (2026-05-20) cerró iteración 1 (esqueleto de 17 CAPs) y Bloque 1 de iteración 2 (6 fichas detalladas: las 4 INFRA + AUTH + INTEG). Quedan Bloques 2 y 3.

### Concepto de "capability" (memorizar antes de retomar)

Una **CAP** es una unidad de funcionalidad con valor coherente para usuario o sistema, descrita a un nivel suficientemente alto como para razonarse como un todo pero suficientemente acotado como para implementarse y verificarse de forma independiente. Es la **capa puente entre la spec HTML y las proposals de OpenSpec**:

```
HTML §6 (use cases)  →  §7 catálogo de CAPs  →  OpenSpec proposals  →  código
```

Una CAP NO es un use case (eso vive en `application/` como código): una CAP suele agrupar varios use cases que forman una feature coherente. Ej.: `CAP-CHATBOT-LIFECYCLE` agrupa `CreateChatbot`, `UpdateChatbot`, `ListChatbots`, `GetChatbot`, `DeleteChatbot` (5 use cases, 1 CAP, 1 proposal).

### Decisiones tomadas (Q7.1–Q7.3)

| Q | Decisión |
|---|---|
| Q7.1 Granularidad | **Por feature de usuario** (~18-25 CAPs en total). 1 CAP agrupa varios use cases relacionados. Mapeable casi 1:1 a OpenSpec proposal. |
| Q7.2 CAPs transversales | **Explícitas dedicadas**: `CAP-INFRA-TENANT-ISOLATION`, `CAP-INFRA-ASYNC-JOBS`, `CAP-INFRA-SECRETS`, `CAP-INFRA-PERSISTENCE` (lista provisional; se ajusta en iteración 1). Otras CAPs las referencian como `deps`. |
| Q7.3 Nivel de detalle | **Mínimo del handover**: por CAP → `id`, `nombre`, `ámbito` (1 línea), `descripción` (2-3 líneas), `deps` (lista de otras CAPs), `use cases mapeados de §6`, `non-goals` (1-2 líneas, "qué NO entra"). Los criterios de aceptación detallados (Given/When/Then) NO van en el catálogo — viven en cada proposal de OpenSpec. |

### Enfoque propuesto (pendiente de confirmación al retomar)

**Formato A — Tarjeta por CAP + bloque resumen al inicio:**
- §7 abre con: (i) mini-tabla `id + nombre` de las ~20 CAPs para vista rápida y (ii) diagrama ASCII/mermaid del grafo de dependencias entre CAPs.
- A continuación, una tarjeta por CAP con los 7 campos del handover, agrupadas por dominio (AUTH → CHATBOT → KB → CHAT → INTEG → WIDGET → EVAL → INFRA).

**Estrategia B — Validación en 2 iteraciones:**
1. **Iteración 1 (esqueleto)**: lista plana de ~20 CAPs con solo `id + nombre + dominio + use cases mapeados`. Una sola decisión: ¿la cobertura es correcta? (¿falta nada, sobra nada, nombres OK?)
2. **Iteración 2 (fichas detalladas)**: una vez fijado el esqueleto, se completan las fichas (descripción + deps + non-goals) y se muestran en 3 bloques por afinidad temática:
   - Bloque 1: **Plataforma y onboarding** — INFRA + AUTH + INTEG
   - Bloque 2: **Definición del chatbot** — CHATBOT + KB + WIDGET
   - Bloque 3: **Runtime y evaluación** — CHAT + EVAL

### Esqueleto cerrado (iteración 1) — 17 CAPs

| # | ID | Dominio |
|---|---|---|
| 1 | `CAP-AUTH-IDENTITY` | AUTH |
| 2 | `CAP-INTEG-CREDENTIALS` | INTEG |
| 3 | `CAP-CHATBOT-LIFECYCLE` | CHATBOT |
| 4 | `CAP-CHATBOT-WIDGET-CONFIG` | CHATBOT |
| 5 | `CAP-KB-LIFECYCLE` | KB |
| 6 | `CAP-KB-DOC-SOURCES` | KB |
| 7 | `CAP-KB-DB-SOURCES` | KB |
| 8 | `CAP-CHAT-AGENT-LOOP` | CHAT |
| 9 | `CAP-CHAT-DOC-RETRIEVAL` | CHAT |
| 10 | `CAP-CHAT-SQL-EXECUTION` | CHAT |
| 11 | `CAP-CHAT-SESSIONS` | CHAT |
| 12 | `CAP-WIDGET-RUNTIME` | WIDGET |
| 13 | `CAP-EVAL-RAGAS` | EVAL |
| 14 | `CAP-INFRA-TENANT-ISOLATION` | INFRA |
| 15 | `CAP-INFRA-ASYNC-JOBS` | INFRA |
| 16 | `CAP-INFRA-SECRETS` | INFRA |
| 17 | `CAP-INFRA-PERSISTENCE` | INFRA |

Decisiones de agrupación que se aplicaron (no re-litigar):
- `CAP-CHAT-AGENTIC-LOOP` propuesto inicialmente como bundle (AnswerQuery+RetrieveDocs+ExecuteSQL) → **se separó en 3 CAPs** (CAP-CHAT-AGENT-LOOP, CAP-CHAT-DOC-RETRIEVAL, CAP-CHAT-SQL-EXECUTION). Razón: riesgos, testing y complejidad muy distintos; Q6.3 los marcó testables aislados.
- `CAP-KB-LIFECYCLE` **mantiene bundled** las ops polimórficas de Sources (ListSources, DetachSource, TestSourceConnection). Razón: son inherentes a "manejar una KB".

Cobertura verificada: 34 UCs §6 + 21 pasos del journey + 4 transversales Q7.2.

### Iteración 2 — Bloque 1 cerrado (6 fichas)

Fichas detalladas redactadas para: `CAP-INFRA-PERSISTENCE`, `CAP-INFRA-TENANT-ISOLATION`, `CAP-INFRA-SECRETS`, `CAP-INFRA-ASYNC-JOBS`, `CAP-AUTH-IDENTITY`, `CAP-INTEG-CREDENTIALS`. Los detalles literales (descripción/deps/non-goals) están en `conversation-2026-05-19.log` bajo "§7 ITERACIÓN 2 — BLOQUE 1".

Grafo de deps del Bloque 1 (sin ciclos): PERSISTENCE → raíz; TENANT-ISOLATION y SECRETS → PERSISTENCE; ASYNC-JOBS → PERSISTENCE+TENANT-ISOLATION; AUTH-IDENTITY → PERSISTENCE+TENANT-ISOLATION+SECRETS; INTEG-CREDENTIALS → SECRETS+TENANT-ISOLATION.

### Próximo paso concreto

Arrancar **Bloque 2 de iteración 2** — fichas detalladas (id, nombre, ámbito, descripción, deps, use cases, non-goals) para los 6 CAPs de **Definición del chatbot**: `CAP-KB-LIFECYCLE`, `CAP-KB-DOC-SOURCES`, `CAP-KB-DB-SOURCES`, `CAP-CHATBOT-LIFECYCLE`, `CAP-CHATBOT-WIDGET-CONFIG`, `CAP-WIDGET-RUNTIME`.

Tras Bloque 2 → Bloque 3 (CHAT + EVAL, 5 fichas). Al cierre de §7, pasar a §8.

---

## 8. Cómo continuar en la próxima sesión

### Estado actual al cierre de sesión 7

**Rama:** `feat/cap-01-infra-persistence` (todo en una rama; cuando se quiera abrir PRs por CAP se rebasarán en branches separadas).

**Plans implementados (12/17):**
| # | CAP | Tag | Estado |
|---|---|---|---|
| 01 | CAP-INFRA-PERSISTENCE | `cap-01-infra-persistence` | ✅ |
| 02 | CAP-INFRA-TENANT-ISOLATION | `cap-02-infra-tenant-isolation` | ✅ |
| 03 | CAP-INFRA-SECRETS | `cap-03-infra-secrets` | ✅ |
| 04 | CAP-INFRA-ASYNC-JOBS | `cap-04-infra-async-jobs` | ✅ (tabla diferida a plan #8) |
| 05 | CAP-AUTH-IDENTITY | `cap-05-auth-identity` | ✅ |
| 06 | CAP-INTEG-CREDENTIALS | `cap-06-integ-credentials` | ✅ |
| 07 | CAP-KB-LIFECYCLE | `cap-07-kb-lifecycle` | ✅ |
| 08 | CAP-KB-DOC-SOURCES | `cap-08-kb-doc-sources` | ✅ (MVP: upload + PDF/TXT + Ollama + fixed_size) |
| 10 | CAP-CHATBOT-LIFECYCLE | `cap-10-chatbot-lifecycle` | ✅ (CRUD + N:M + RESTRICT FK + embedding compat) |
| 12 | CAP-CHAT-DOC-RETRIEVAL | `cap-12-chat-doc-retrieval` | ✅ (RetrieveDocs + utility endpoint `/search`) |
| 14 | CAP-CHAT-SESSIONS | `cap-14-chat-sessions` | ✅ (sessions/messages + read endpoints + helpers para #15) |
| 15 | CAP-CHAT-AGENT-LOOP | `cap-15-chat-agent-loop` | ✅ **M3 CERRADO** (LLM port + Ollama adapter + agent loop + `POST /chat`) |

**Cambio de orden frente al catálogo:** hemos saltado #9 (KB-DB-SOURCES, M4) y #11 (WIDGET-CONFIG) para priorizar la demo M3 (chatbot que responde sobre los docs de M2). El usuario lo confirmó en sesión 6.

**M1 + M2 + M3 cerrados.** Lo que funciona end-to-end contra el stack vivo: register → KB con embedding Ollama → upload PDF/TXT → ingestion async con polling → chunks en Qdrant → CRUD de chatbots con validación cross-KB de embedding → sesiones de chat con cascada → **`POST /api/chatbots/{id}/chat` ejecuta el agent loop con llama3.1, llamando `search_docs` y devolviendo respuesta con citas reales y telemetría por iteración**. Demo verificada en sesión 7: pregunta sobre la guerra civil española → respuesta menciona 1939 + cita manual.txt.

**Verificación al cierre de sesión 7 (stack Docker vivo):**
- `ruff check .` ✅ All checks passed
- `mypy src/` ✅ Success: no issues found in 143 source files
- `pytest tests/unit` ✅ **138 passed**
- `pytest tests/integration -m integration` ✅ **28 passed** contra Postgres + Qdrant + Ollama (llama3.1 + bge-m3)

**Bugs reales encontrados y arreglados en sesión 6:**
- **`bootstrap_tenant` FK ordering** (commit `e21c658`): SQLAlchemy no detecta la dependencia de INSERT entre `TenantRow` y `ProviderCredentialRow` sin un `relationship()` declarado, así que emitía el credential primero → `ForeignKeyViolationError`. Fix: flush intermedio entre `session.add(tenant)` y `session.add(credential)`. Lo descubrieron los integration tests en cuanto Docker estuvo arriba — los unit tests no lo cogieron porque mockean el repo.
- **`session.flush()` vs `session.commit()` en endpoints de upload + reindex** (plan #8 Task 5, fix dentro del commit `e88d6dc`): los endpoints hacían `flush()` antes de programar el background task. La corutina background abría su propia sesión y trataba de leer el `IngestionJobRow` antes de que la transacción de request se hubiera commiteado → "row not found". Fix: `flush()` → `commit()` en ambos endpoints.
- **`qdrant-client 1.18.0` cambió la API** (commit `c80c7cd`): `.search()` eliminado a favor de `.query_points()`. El subagent del plan #12 lo migró internamente sin cambiar la firma de `QdrantStore.search`. Solo se descubrió al correr el test e2e contra Qdrant real.
- **Tests de migración stale relajados:** `test_alembic_baseline_marks_db` y `test_users_tenants_migration` asseraban `version_num == "0001"/"0002"`. Ahora verifican el side-effect (versión no-null + tablas presentes), no la revisión congelada. Plans futuros que añadan migración no los rompen.

**Bugs reales encontrados y arreglados en sesión 7 (plan #15):**
- **`httpx.BaseTransport` vs `AsyncBaseTransport`** (commit `226db16`, ollama.py:32): el adapter declaró `transport: httpx.BaseTransport | None` pero httpx.AsyncClient requiere `AsyncBaseTransport`. mypy lo cazó al pase de cleanup; httpx.MockTransport implementa ambos así que los unit tests no notaban nada en runtime.
- **Llama3.1 no presente al primer intento de Task 5**: el contenedor `tfm-rag-ollama-1` arrancó sin modelos (volumen reciente). Subagent reportó BLOCKED. El usuario hizo `ollama pull llama3.1` en el host Ollama nativo. ANOTACIÓN IMPORTANTE: lo que mira la app NO es el contenedor Ollama, es **el Ollama nativo del host** (port 11434 binding gana el suyo). El contenedor está sombreado. Esto resuelve definitivamente el "Ollama dual potencial" que estaba como riesgo abierto en handovers previos.

**Hacks legítimos consolidados como patrones del repo:**
- **`func.__test__ = False`** cuando un use case se llama `test_*` (porque el spec dice `TestX`) y el test file lo importa directamente. Plan #6 no lo necesitó porque `test_credential` solo se importa desde el router; plan #7 lo necesitó para `test_source_connection`.
- **`metadata_` mapeado a columna `metadata`**: SQLAlchemy reserva el atributo `metadata` en `Base`. En `ChatMessageRow` (plan #14) el atributo Python es `metadata_` con `mapped_column("metadata", JSONB, ...)`. Use cases traducen a `metadata` (sin underscore) en la salida HTTP.
- **`_deps._session_factory = None` en fixtures de integration tests de routers** (plan #7+): el `_session_factory` global en `infrastructure/api/dependencies.py` queda acoplado al primer event loop. Con `asyncio_mode=auto` (loop por test) hay clash cross-loop. Reset en la fixture de cleanup. Nota arquitectónica: refactor candidato a `app.state.session_factory` en lifespan FastAPI — sigue pendiente.

**Notas de operación del stack:**
- **STORAGE_LOCAL_PATH default es `/data/storage` y requiere root.** Override con `STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage'` para correr localmente. El `scripts/setup.sh` lo hace automáticamente al generar `.env`.
- **Ollama dual potencial**: en WSL2 puede haber un Ollama nativo en el host *y* el contenedor `tfm-rag-ollama-1` (port 11434 ambos). Si los embeddings fallan, verifica con `curl localhost:11434/api/tags` qué instancia responde. La que ganó el port en sesión 6 fue la nativa del host — funciona igual mientras tenga `bge-m3` y `llama3.1` pulled.
- **`python-multipart>=0.0.9`** añadido en plan #8 como dep (lo requiere FastAPI para `File`/`Form` uploads).
- **Scripts de bootstrap creados (sesión 6):** `scripts/setup.sh` (instalación idempotente en PC nuevo) + `scripts/run-backend.sh` (arrancar uvicorn con las env vars correctas). README en raíz reescrito como entry point completo.

**Plans pendientes (5/17):** #9 KB-DB-SOURCES (M4) → #11 CHATBOT-WIDGET-CONFIG → #13 CHAT-SQL-EXECUTION → #16 WIDGET-RUNTIME → #17 EVAL-RAGAS. Todos ortogonales a la demo M3 ya operativa.

### Workflow de ejecución acordado con el usuario

Para minimizar interrupciones (confirmado y validado en sesión 6):
- **Una sola rama** por ahora (`feat/cap-01-infra-persistence`); cuando el usuario quiera PRs separados, hacer rebase por CAP.
- **Subagent-driven** con dispatches por batches de 2-3 tareas (haiku para tareas mecánicas, sonnet para integración).
- **NO correr ruff/mypy/pytest dentro de subagents** — el controller hace un pase global al final del plan (cleanup commit cuando haga falta + tag movido al cleanup).
- **NO usar reviewers (spec/quality) salvo dudas serias** — son demasiado caros para el ritmo del TFM.
- Cada subagent puede dejar dudas en `subagent-questions.md` (formato en cabecera). El controller cierra las dudas al final del plan con respuesta `✅ Aceptada`.

### Próximo paso concreto en la siguiente sesión

1. Saluda y confirma que lees handover.
2. Verifica Docker arriba (`docker compose ps` desde `infra/`). Si no, `bash scripts/setup.sh`. **OJO**: el Ollama que la app usa es el del HOST (no el container), así que confirma `ollama list` desde el host también muestra `llama3.1` + `bge-m3`. Si no, `ollama pull llama3.1` + `ollama pull bge-m3`.
3. Pregunta al usuario qué plan toca. Lista priorizada según valor de demo:
   - **#11 (CHATBOT-WIDGET-CONFIG)** + **#16 (WIDGET-RUNTIME)**: abren una demo pública con widget embebible — visible, vendible. Buena candidata para enseñar al tribunal.
   - **#9 (KB-DB-SOURCES)** + **#13 (CHAT-SQL-EXECUTION)**: amplía RAG a sources SQL — agrega valor técnico pero la demo M3 ya cubre el grueso del TFM.
   - **#17 (EVAL-RAGAS)**: harness de evaluación con métricas — es lo que pide la rúbrica de proyecto si va a haber un "capítulo de evaluación".
4. Una vez elegido, sigue el workflow del handover (writing-plans → subagent-driven-development → cleanup + tag).

**M3 está hecho** — los siguientes plans son ortogonales a la demo principal.

### Pendientes / riesgos conocidos

- **Docker WSL2 operativo** — `docker compose up -d postgres qdrant ollama` desde `infra/` funciona. Ollama image (~3.86 GB) descargada y volúmenes persistentes.
- **Tags movidos tras cleanup (convención consolidada)** — todos los `cap-NN-*` apuntan al commit `chore(plan-NN): ruff autofix` final, no al `feat:` original. Última secuencia: cap-07 → e56950c, cap-08 → f545631, cap-10 → c23e5e4, cap-12 → c9aa7c2, cap-14 → db689b5, cap-15 → 226db16.
- **Branch `feat/cap-01-infra-persistence`** acumula 11 CAPs. Cuando se quiera abrir PRs separadas, rebasear en branches por tag.
- **`_session_factory` global** en `infrastructure/api/dependencies.py` — sigue pendiente el refactor a `app.state.session_factory` en lifespan FastAPI. Cada vez que un test de integración nuevo toca routers necesita resetearlo en su fixture.
- **Qdrant client 1.18.0 vs server 1.12.0** — warning en cada llamada; no bloqueante. La librería ya migró internamente de `.search()` a `.query_points()` (visto en plan #12).
- **Ollama dual CONFIRMADO** — instancia nativa en host *y* container `tfm-rag-ollama-1` ambos intentan port 11434. **La nativa del host gana siempre**; el container está sombreado. Por tanto los modelos hay que pull-earlos en el host (`ollama pull llama3.1` desde el host, NO desde dentro del contenedor). Sesión 7 lo confirmó al desbloquear Task 5 de plan #15.
- **VOs `Citation` + `RetrievalIteration` ahora con shapes oficiales** (plan #15). El JSONB de `chat_messages.citations` sigue el `Citation.to_dict()` y `chat_messages.metadata.iterations[i]` sigue `RetrievalIteration.to_dict()`. Cualquier code path que lea esos campos debe hidratarlos vía `.from_dict()`.
- **Plan #8 OUT OF SCOPE pendiente como expansión horizontal:** cloud DocumentSource (gdrive/s3), loaders extra (docx/csv/md/xlsx), embedder `openai_compat`. La arquitectura (ports + LoaderDispatcher + EmbedderDispatcher) está lista — solo nuevos adapters registrados.
- **Plan #12 OUT OF SCOPE pendiente:** reranker adapters (`BGECrossEncoderReranker`, `CohereRerankerAdapter`). El puerto está definido; `retrieve_docs` acepta un `Reranker` instance opcional.

### Endpoints HTTP operativos al cierre de sesión 6

```
GET    /health
POST   /api/auth/register
POST   /api/auth/login
POST   /api/auth/login/google
GET    /api/providers/llm
GET    /api/providers/embedding
GET    /api/credentials
POST   /api/credentials
DELETE /api/credentials/{id}
POST   /api/credentials/{id}/test
POST   /api/knowledge-bases
GET    /api/knowledge-bases
GET    /api/knowledge-bases/{kb_id}
PATCH  /api/knowledge-bases/{kb_id}
DELETE /api/knowledge-bases/{kb_id}
GET    /api/knowledge-bases/{kb_id}/sources
DELETE /api/knowledge-bases/{kb_id}/sources/{source_id}
POST   /api/knowledge-bases/{kb_id}/sources/test-connection
POST   /api/knowledge-bases/{kb_id}/sources/documents     (multipart upload)
POST   /api/knowledge-bases/{kb_id}/sources/{src_id}/reindex
POST   /api/knowledge-bases/{kb_id}/search                (plan #12 — busca chunks)
GET    /api/ingestion-jobs/{job_id}
POST   /api/chatbots
GET    /api/chatbots
GET    /api/chatbots/{chatbot_id}
PATCH  /api/chatbots/{chatbot_id}
DELETE /api/chatbots/{chatbot_id}
GET    /api/chatbots/{chatbot_id}/sessions                (plan #14)
GET    /api/sessions/{session_id}                         (plan #14)
POST   /api/chatbots/{chatbot_id}/chat                    (plan #15 — agent loop)
```

**Demo M3 cerrada — todos los endpoints HTTP del MVP están en producción.**

### Cómo ejecutar el stack manualmente (cuando Docker esté disponible)

```bash
cd infra
cp .env.example .env
# Generar secretos:
python -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(32))" >> .env
python -c "from cryptography.fernet import Fernet; print('FERNET_KEY=' + Fernet.generate_key().decode())" >> .env
docker compose up -d postgres qdrant ollama
cd ../backend
source .venv/bin/activate
alembic upgrade head
pytest tests/integration -m integration -v
uvicorn tfm_rag.infrastructure.api.app:app --reload --port 8000
# En otra terminal:
curl http://localhost:8000/health
curl -X POST http://localhost:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"test@example.com","password":"password123"}'
```

---

## 9. Forma de trabajar acordada

- **Update log periódicamente** sin esperar a que el usuario lo pida (preferencia explícita en memoria).
- **Presentar por bloques** y validar antes de avanzar.
- **No re-litigar** decisiones cerradas a menos que el usuario lo pida explícitamente.
- **Idioma:** todo el trabajo escrito (HTML, log, código) en español; identificadores de código y nombres de clase en inglés.
- **Pivots arquitectónicos legítimos**: si una decisión en una sección obliga a rectificar secciones anteriores ya "cerradas", se documenta en este handover (§5) y se aplica al escribir el HTML — no se re-presenta cada sección anterior.

---

## 10. Estado del TaskList

```
#1-#7  [completed] Diseño (15 secciones HTML + 10 preguntas
                   respondidas + writing-plans invocado)
#8     [in_progress] Escribir + implementar 17 plans (12/17 hechos)
                     ✅ Plans 01-06 (M1 cerrado, todos tagged + E2E verificado)
                     ✅ Plans 07-08 (M2 demo MVP — KB CRUD + ingestion + Qdrant)
                     ✅ Plans 10, 12, 14, 15 (M3 CERRADO — chatbots + retrieval + sessions + agent loop)
                     ⏳ Plans 09, 11, 13, 16, 17 (M4-M7, ortogonales a la demo principal)
#9     [completed]   Ejecutar integration tests con Docker disponible
                     (12/12 → 17/17 → 20/20 → 25/25 → 28/28 — sesión 7)
#10    [pending]     PR(s) — decidir si uno por CAP o uno por M
#11    [completed]   Bootstrap scripts + README + run-backend.sh (sesión 6)
```

Estado actual: en pausa para handover. **M3 demo está operativa**: la siguiente sesión puede iniciar cualquiera de los plans M4-M7 según prioridad del usuario.
