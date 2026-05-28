# Code Review Report — 6 Stacked Milestone PRs

**Fecha:** 2026-05-28
**Ramas analizadas:** `m1-infra`, `m2-docs`, `m3-chat`, `m4-sql`, `m5-widget`, `m6-eval`

---

## Resumen Ejecutivo

| Severidad | Cantidad |
|-----------|----------|
| CRITICO   | 6        |
| ALTO      | 9        |
| MEDIO     | 16       |
| BAJO      | 8        |
| Dependencias | 2     |

**Top 3 arreglos urgentes:**
1. SQL injection via CTE con DML (`sql_safety.py`)
2. Path traversal en `LocalStorage.load/delete`
3. Google OAuth crea usuarios duplicados

---

## CRITICOS

### C1. SQL injection via CTE con DML — `sql_safety.py`
**Rama:** m4-sql | **Archivo:** `backend/src/tfm_rag/application/chat/sql_safety.py:24-30`

El regex `_BANNED_TOKEN_RE` no detecta DML dentro de CTEs. Un LLM podría emitir:
```sql
WITH evil AS (DELETE FROM users RETURNING *) SELECT * FROM evil
```
El verbo principal es `WITH` (pasa `_LEADING_VERB_RE`), y aunque `DELETE` aparece en el texto, la dependencia de regex para detectar DML en CTEs es frágil. PostgreSQL permite DML en CTEs con `RETURNING`.

**Fix:** Rechazar cláusulas `WITH` que contengan keywords de DML en su body, o usar un parser SQL real.

---

### C2. Path traversal en `LocalStorage.load/delete`
**Rama:** m2-docs | **Archivo:** `backend/src/tfm_rag/infrastructure/storage/local.py:45-54`

`storage_uri` se usa directamente sin validar que la ruta resuelta esté dentro de `self._root`. Un atacante podría:
```
file:///etc/passwd
file://../../etc/shadow
```
**Fix:** Validar `path.resolve().startswith(self._root.resolve())`.

---

### C3. Sin límite de tamaño en upload
**Rama:** m2-docs | **Archivo:** `backend/src/tfm_rag/infrastructure/api/routers/knowledge_bases.py:upload`

`await file.read()` sin límite. Un archivo de varios GB causa OOM.
**Fix:** Agregar `MAX_UPLOAD_BYTES` y validar antes de leer.

---

### C4. CORS echo-back en widget — `widget_cors.py`
**Rama:** m5-widget | **Archivo:** `backend/src/tfm_rag/application/chat/widget_cors.py:30-34`

Cuando `allowed_origins` está vacío, el resolver devuelve cualquier origin. Con `Allow-Credentials: true`, cualquier sitio puede hacer requests autenticados al widget.
**Fix:** Cuando `allowed_origins` está vacío, retornar `None` (bloquear CORS).

---

### C5. Google OAuth crea usuario duplicado
**Rama:** m1-infra | **Archivo:** `backend/src/tfm_rag/application/auth/login_with_google.py:36-43`

Si un usuario se registró con email/password (sin `google_sub`), `find_by_google_sub` retorna `None` y se crea un segundo usuario con el mismo email → `IntegrityError` 500.
**Fix:** Buscar por email primero; si existe, vincular `google_sub` en vez de crear nuevo usuario.

---

### C6. SSRF via `base_url` de credenciales
**Rama:** m1-infra | **Archivo:** `backend/src/tfm_rag/application/integrations/test_credential.py:45-53`

`base_url` es controlada por el usuario. Un atacante puede apuntar a:
- `http://169.254.169.254/latest/meta-data/` (metadata cloud)
- IPs internas de red

No hay allowlist ni bloqueo de IPs privadas.
**Fix:** Validar que `base_url` no apunte a rangos de IP privada o metadata endpoints.

---

## ALTOS

### H1. Upsert nunca actualiza — `upsert_provider_credential.py`
**Rama:** m1-infra | **Archivo:** `backend/src/tfm_rag/application/integrations/upsert_provider_credential.py:52-58`

Siempre crea fila nueva con `uuid4()`. Si existe una credencial con el mismo `(provider_id, label)`, lanza `IntegrityError` 500.
**Fix:** Buscar existente antes de crear; si existe, actualizar en vez de crear.

---

### H2. Health crea engine nuevo por request
**Rama:** m1-infra | **Archivo:** `backend/src/tfm_rag/infrastructure/api/routers/health.py:36-42`

Cada health check crea+destruye un engine SQLAlchemy con pool de conexiones. Bajo carga agota `max_connections`.
**Fix:** Reutilizar el engine de la aplicación via dependency injection.

---

### H3. Sin rate limiting en `/chat`
**Rama:** m3-chat | **Archivo:** `backend/src/tfm_rag/infrastructure/api/routers/chatbots.py:292`

Cada request ejecuta hasta 5 llamadas LLM sin throttling. Abuso de GPU/costos.
**Fix:** Implementar rate limiter (slowapi o Redis token bucket).

---

### H4. Agent loop sin budget de contexto
**Rama:** m3-chat | **Archivo:** `backend/src/tfm_rag/application/chat/answer_query.py:131-166`

Acumula mensajes sin límite de tokens. Con 3 iteraciones × 5 chunks de 600 chars = ~12K chars de tool results + 8K del usuario + system prompt puede exceder context windows pequeños.
**Fix:** Agregar `max_context_chars` guard o truncar resultados más antiguos.

---

### H5. Credenciales de sesión en `localStorage`
**Rama:** m5-widget | **Archivo:** `widget/widget.js:51-73`

`cookie` y `session_id` se almacenan en `localStorage`. Cualquier JS del host page puede leerlos.
**Fix:** Mover credenciales a HttpOnly cookie. `localStorage` solo para historial de mensajes.

---

### H6. CORS middleware omite headers del padre
**Rama:** m5-widget | **Archivo:** `backend/src/tfm_rag/infrastructure/api/middleware/widget_cors.py:43-50`

Cuando la ruta setea `Allow-Origin`, el middleware no incluye `Allow-Methods`, `Allow-Headers`, `Vary`. Preflights fallan.
**Fix:** Inyectar headers faltantes aunque se preserve el origin de la ruta.

---

### H7. Qdrant client creado por request
**Rama:** m2-docs | **Archivo:** `backend/src/tfm_rag/infrastructure/api/routers/knowledge_bases.py:131-134`

`QdrantStore` se instancia y destruye por request. Agota conexiones TCP.
**Fix:** Singleton Qdrant inyectado via FastAPI dependencies.

---

### H8. Embeddings secuenciales en Ollama
**Rama:** m3-chat | **Archivo:** `backend/src/tfm_rag/infrastructure/embedders/ollama.py:20-31`

Cada chunk se embebe con un HTTP separado. Ingesta de documentos grandes extremadamente lenta.
**Fix:** Usar `/api/embed` batching o documentar como limitación conocida.

---

### H9. Background ingestion no verifica existencia de KB/source
**Rama:** m2-docs | **Archivo:** `backend/src/tfm_rag/infrastructure/api/routers/knowledge_bases.py:_ingest_in_background`

Si se borran KB/source antes de la ingesta, `scalar_one()` falla silenciosamente. Job queda en `queued` para siempre.
**Fix:** Catch `NoResultFound` y marcar job como `failed`.

---

## MEDIOS

| # | Rama | Archivo | Problema |
|---|------|---------|----------|
| M1 | m1 | `tenant_scoping.py:56` | JSON injection en error responses — `str(exc)` en JSON manual. |
| M2 | m1 | `dependencies.py:15` | Race condition en `_session_factory` global sin lock. |
| M3 | m1 | `auth.py:22` | Sin validación de fuerza de password (acepta vacío). |
| M4 | m1 | `auth.py:68` | User enumeration via `UserAlreadyExistsError`. |
| M5 | m1 | `credentials.py:126` | `delete_credential` catchea `Exception` bare → 404. |
| M6 | m2 | `knowledge_bases.py:_ingest` | Hardcodea `embedder_api_key=None` ignora credenciales. |
| M7 | m2 | `fixed_size.py:33` | Chunker produce chunks duplicados en edge cases. |
| M8 | m3 | `list_chatbots.py:32` | N+1 query — `list_kb_ids` por cada chatbot. |
| M9 | m3 | `answer_query.py:126` | Hardcodea `base_url = ollama_base_url` ignora credenciales. |
| M10 | m3 | `ollama.py:31` | Nuevo `httpx.AsyncClient` por cada llamada LLM. |
| M11 | m3 | `pipeline_config.py:26` | `max_tokens` permite hasta 32,000. |
| M12 | m4 | `sql_safety.py:24` | Regex falsos positivos en identificadores (`delete_log`). |
| M13 | m4 | `system_prompt.py:40` | Schema de BD inyectado sin sanitizar en prompt. |
| M14 | m5 | `public_chat.py:110` | Sin `min_length/max_length` en `PublicChatIn.message`. |
| M15 | m5 | `widget_config.py:20` | Origin regex acepta `http://` (inseguro). |
| M16 | m6 | `report_writer.py:57` | Archivos de reporte se sobreescriben sin aviso. |

---

## DEPENDENCIAS

| # | Rama | Problema |
|---|------|----------|
| D1 | m1 | `python-jose[cryptography]` deprecated con CVEs → usar `PyJWT`. |
| D2 | m6 | `langchain-ollama>=0.2` sin upper bound → pin a `<0.3`. |

---

## Estrategia de Arreglo

Los branches están stacked: `m1 → m2 → m3 → m4 → m5 → m6`. Cada branch hereda los cambios de los anteriores.

**Plan de ejecución:**
1. Crear branch `fix/all-reviews` desde `m5-widget` (el más avanzado con código completo)
2. Aplicar todos los fixes de m1 a m6 en commits separados
3. Cada fix será atómico y descriptivo

**Archivos a modificar por branch:**

### m1-infra (9 fixes)
- `sql_safety.py` — CTE-DML bypass (→ m4, pero fix base en m1 patterns)
- `upsert_provider_credential.py` — upsert roto
- `test_credential.py` — SSRF
- `login_with_google.py` — duplicate user
- `widget_cors.py` — echo-back
- `health.py` — engine per request
- `tenant_scoping.py` — JSON injection
- `auth.py` — password validation + user enum
- `dependencies.py` — race condition

### m2-docs (5 fixes)
- `local.py` — path traversal
- `knowledge_bases.py` — upload size + background ingestion
- `qdrant_client.py` — singleton pattern
- `fixed_size.py` — chunker duplicates

### m3-chat (6 fixes)
- `answer_query.py` — context budget + hardcoded base_url
- `list_chatbots.py` — N+1
- `ollama.py` (embedder) — batch
- `ollama.py` (LLM) — client reuse
- `pipeline_config.py` — max_tokens

### m4-sql (3 fixes)
- `sql_safety.py` — false positives + CTE
- `system_prompt.py` — injection
- `query_database.py` — docstring

### m5-widget (4 fixes)
- `widget_cors.py` — echo-back
- `public_chat.py` — validation
- `widget_cors.py` (middleware) — headers
- `widget_config.py` — http regex

### m6-eval (3 fixes)
- `report_writer.py` — overwrite
- `dataset_loader.py` — strip
- `pyproject.toml` — pin
