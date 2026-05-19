# Handover — sesión de brainstorming TFM RAG Platform

**Cerrado:** 2026-05-19. **Continuación:** próxima sesión.

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
- **Code samples literales de la sesión**: `code-samples-2026-05-19.md` (raíz del repo) — entidades, puertos, adaptadores, catálogo y composition root en Python ejecutable
- **Este handover**: `handover.md` (raíz del repo)
- **HTML final** (cuando se escriba): `docs/superpowers/specs/2026-05-19-tfm-roadmap-funcional-design.html`

Hay una memoria global guardada en `~/.claude/projects/-home-acabo-personal-tfmragapp/memory/` con la preferencia "actualiza el .log periódicamente sin que te lo pida". Respétala.

---

## 3. Estado de las 15 secciones del documento

| # | Sección | Estado |
|---|---|---|
| 1 | Visión, glosario y supuestos | ✅ Aprobada |
| 2 | Mapa de módulos y dependencias | ✅ Aprobada (cohesionada con journey de 20 pasos) |
| 3 | Flujos end-to-end (A–G) | ✅ Aprobada |
| 4 | Dominio: entidades, value objects, contratos Python, errores | ✅ **Cerrada** |
| 5 | Adaptadores MVP | 🟡 **Presentada, esperando 3 respuestas** (Q5.1, Q5.2, Q5.3) |
| 6 | Casos de uso / servicios de aplicación | ⏳ Pendiente |
| 7 | Catálogo de capabilities (CAP-*) — fuente para OpenSpec | ⏳ Pendiente (sección clave) |
| 8 | API REST (endpoints, req/resp) | ⏳ Pendiente |
| 9 | Modelo de datos (Postgres + Qdrant) | ⏳ Pendiente |
| 10 | Panel (sitemap + wireframes) | ⏳ Pendiente |
| 11 | Widget embebible | ⏳ Pendiente |
| 12 | Seguridad y multi-tenancy | ⏳ Pendiente |
| 13 | Evaluación (RAGAS) | ⏳ Pendiente |
| 14 | Roadmap M1–M7 | ⏳ Pendiente |
| 15 | Riesgos y mitigaciones | ⏳ Pendiente |

---

## 4. Preguntas pendientes de la Sección 5 (responder primero al retomar)

### Q5.1 — Extensiones de archivo soportadas en MVP

Actual: **PDF, DOCX, TXT, CSV, MD**. ¿Añadir XLSX/JSON/HTML, o cerrar en estas 5?
**Recomendación:** cerrar en 5; XLSX y HTML como línea futura.

### Q5.2 — Conectores cloud en MVP

Actual: **Google Drive + S3 + Dropbox**. ¿Los tres, o reducir?
**Recomendación:** dejar 2 (Google Drive + S3); Dropbox como extensión. Cada conector vale ~1 día de implementación.

### Q5.3 — Engines SQL en MVP

Actual: **Postgres + MySQL**. ¿Ambos, o sólo Postgres?
**Recomendación:** ambos. MySQL es trivial sobre SQLAlchemy Core y demuestra mejor la modularidad del puerto.

---

## 5. Decisiones ya tomadas (no re-litigar)

| Eje | Decisión |
|---|---|
| Tipo de documento | Funcional detallado + roadmap M1-Mn en HTML autocontenido con nav lateral |
| Audiencia del HTML | Ade (visualizar) + agentes (implementar). **Spec ejecutable, no documento estético.** |
| Origen para OpenSpec | Sección 7 — catálogo de capabilities con IDs `CAP-*` |
| Tenancy | Multi-tenant real. 1 admin = 1 tenant en MVP (sin invitaciones de miembros) |
| Auth | Email+password + Google OAuth opcional. NextAuth en frontend; backend verifica id_token y emite JWT propio |
| Contratos de puertos | Firmas Python completas (ABC, tipos, errores) |
| Catálogo de proveedores | Vive **en código** (`domain/catalog/llm_providers.py`). No hay superadmin. Añadir proveedor = código nuevo |
| Tipos de credencial | `config_source = SERVER_ENV` (Ollama, en `.env` del sysadmin) o `TENANT_CREDENTIAL` (OpenAI, OpenAI-compat) |
| Widget | Configurador en panel + preview en vivo + snippet copiable. Bundle JS vanilla independiente en `widget/` |
| Config pipeline | Modo Simple (preset por tipo de contenido) y Avanzado (chunking, top-k, threshold, modo router) |
| Upload de archivos | Drag&drop en panel + conectores cloud |
| Async ingesta | FastAPI BackgroundTasks + tabla `ingestion_jobs` + polling desde panel |
| Conversación | Multi-turno con `session_id` persistido en BD |
| Repo layout | `backend/` + `frontend/` + `widget/` + `infra/` + `scripts/` |
| System prompt | Textarea libre + plantillas opcionales |
| Router | LLM con function calling. `router_llm` opcional para usar modelo más barato |
| API keys | Por tenant (no por chatbot). Cifradas con Fernet |
| Sesión JWT | Corta (1h). Sin revocación en BD en MVP |
| Granularidad roadmap | Hitos end-to-end M1-Mn demo-ables (no por semana) |
| Texto de chunks | Sólo en payload de Qdrant + referencia (source_id, page, char_start/end) |
| Citas en ChatMessage | Sólo referencia, sin texto literal. Resolución del texto bajo demanda vía `chunk_id` → Qdrant |
| `ChatMessage.tokens_in/out/latency_ms` | Mantenidos (alimentan métricas operacionales del TFM) |

---

## 6. Nomenclatura clave (memorizar antes de retomar)

```
LLMProvider              # Puerto (ABC)
OllamaLLMAdapter         # Adapter concreto
OpenAILLMAdapter         # Adapter concreto
OpenAICompatLLMAdapter   # Adapter concreto genérico (Groq, Together, etc.)
LLMProviderDescriptor    # Metadata en el catálogo
LLM_PROVIDER_CATALOG     # dict {provider_id: (Descriptor, adapter_class)}
ProviderCredential       # BD, por tenant (api_key cifrada, base_url opcional)
LLMSelection             # Value object dentro de Chatbot: {provider_id, credential_id, model_id}
```

Análogo para `EmbeddingProvider`, `CloudStorageConnector`, `SQLDataSource`.

`Tenant` es el espacio aislado. En MVP es 1:1 con `User` (invisible en UI) pero existe en el modelo para aislamiento real (filtros BD, colecciones Qdrant físicas, storage prefix).

---

## 7. Cómo continuar en la próxima sesión

1. **Saluda al usuario** y confirma que vienes de leer `handover.md`.
2. **Pregunta Q5.1, Q5.2, Q5.3** (puedes batchearlas en un AskUserQuestion único — son tres elecciones independientes).
3. Cuando las apruebe, **actualiza el log** con la resolución y márcalo en el log como "Sección 5 CERRADA".
4. **Continúa con Sección 6** (casos de uso / servicios de aplicación). Sigue el patrón: presentar, esperar feedback, ajustar, cerrar, actualizar log.
5. **Actualiza el `.log` después de cada sección cerrada** (no esperes a que te lo pidan — está como feedback memory).
6. Cuando las 15 estén cerradas:
   - Escribe el HTML final en `docs/superpowers/specs/2026-05-19-tfm-roadmap-funcional-design.html`.
   - Haz el spec self-review (placeholder/consistencia/scope/ambigüedad).
   - Pídele al usuario que lo revise.
   - Invoca **`writing-plans`** para generar el plan de implementación. No invoques ninguna otra skill.

---

## 8. Forma de trabajar acordada

- **Update log periódicamente** sin esperar a que el usuario lo pida (preferencia explícita guardada en memoria).
- **Presentar por bloques** y validar antes de avanzar.
- **No re-litigar** decisiones cerradas a menos que el usuario lo pida explícitamente.
- **Idioma:** todo el trabajo escrito (HTML, log, código) es en español, salvo identificadores de código y nombres de clase que van en inglés.

---

## 9. Estado del TaskList

```
#1 [completed] Explorar contexto del proyecto
#2 [completed] Hacer preguntas clarificadoras al usuario
#3 [completed] Proponer 2-3 estructuras del documento
#4 [in_progress] Presentar diseño por secciones y obtener aprobación
#5 [pending] Escribir documento HTML final
```

Task #4 sigue activa: aún quedan 10 secciones (5 esperando aprobación + 6 a 15 pendientes).
