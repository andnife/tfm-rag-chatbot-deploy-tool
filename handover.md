# Handover — sesión de brainstorming TFM RAG Platform

**Última actualización:** 2026-05-20, sesión 4 (15 secciones CERRADAS + HTML escrito + questions-pending.md respondido + HTML actualizado con las decisiones del usuario).
**Continuación:** invocar `writing-plans` para generar el plan de implementación; tras eso, extraer las 17 OpenSpec proposals en orden del grafo de deps.

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

15 secciones cerradas, HTML escrito y actualizado con las 10 decisiones del usuario (P-01 a P-10). **Próximo paso: invocar `writing-plans`** para generar el plan de implementación.

1. **Saluda al usuario** y confirma que vienes de leer `handover.md`.
2. Verifica que el HTML está al día: `docs/superpowers/specs/2026-05-19-tfm-roadmap-funcional-design.html`.
3. Lee `questions-pending.md` para conocer las decisiones aplicadas (cabecera con resumen + cuerpo histórico con las respuestas literales).
4. Invoca **`writing-plans`** para generar el plan de implementación. No invoques ninguna otra skill.
5. El plan debe orquestar la extracción de las **17 OpenSpec proposals** (1 CAP → 1 proposal) en orden del grafo de deps:
   - **Plataforma:** PERSISTENCE → TENANT-ISOLATION → SECRETS → ASYNC-JOBS → AUTH-IDENTITY → INTEG-CREDENTIALS
   - **Definición:** KB-LIFECYCLE → KB-DOC-SOURCES → KB-DB-SOURCES → CHATBOT-LIFECYCLE → CHATBOT-WIDGET-CONFIG
   - **Runtime:** CHAT-DOC-RETRIEVAL → CHAT-SQL-EXECUTION → CHAT-SESSIONS → CHAT-AGENT-LOOP → WIDGET-RUNTIME
   - **Evaluación:** EVAL-RAGAS
6. Orden de implementación recomendado por el usuario (P-01): M1 → M2 → M3 → M4 → **M6 (RAGAS)** → M5 (widget) → M7 (pulido opcional). Adelantar M6 antes de M5 permite medir el sistema en cuanto haya runtime.

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
#1 [completed] Explorar contexto del proyecto
#2 [completed] Hacer preguntas clarificadoras al usuario
#3 [completed] Proponer 2-3 estructuras del documento
#4 [completed] Presentar diseño por secciones y obtener aprobación
               (1-15 cerradas — §7 con 17 CAPs; §8-§15 drafteadas
                autónomamente en modo /goal)
#5 [completed] Escribir documento HTML final
#6 [completed] Self-review del HTML
#7 [completed] Revisión por el usuario (HTML + questions-pending.md
                respondido con 10 decisiones aplicadas al HTML)
#8 [in_progress] Invocar writing-plans
                  → Plan #1 (CAP-INFRA-PERSISTENCE) escrito en
                    docs/superpowers/plans/2026-05-20-01-...md
                  → Quedan 16 plans (02..17) por escribir, en orden
                    del grafo de deps.
#9 [pending]   Ejecutar plans (subagent-driven o inline)
```

Task #7 es el gate actual.
