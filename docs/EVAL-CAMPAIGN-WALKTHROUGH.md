# Campaña de evaluación RAGAS — qué pasa, paso a paso

> Objetivo: saber **exactamente** qué modelos actúan, en qué acción, qué se mide, qué cuesta y qué obtienes — para revisar que todo está listo **antes** de poner una API de pago (primero se prueba con NVIDIA free).

## 1. Qué mide la campaña
Evalúa el **pipeline RAG agéntico** del chatbot contra un dataset de preguntas con respuesta de referencia (`ground_truth`). Cada pregunta tiene un **escenario**: `doc_only` (respuesta en documentos), `sql_only` (en la BD), `mixed` (ambos) o `abstain` (no contestable → debe abstenerse). Se puntúa con **RAGAS** (LLM-as-judge) + métricas deterministas.

## 2. Actores (modelos) y su papel
| Actor | Qué hace | Modelo | Coste |
|---|---|---|---|
| **Generación — evaluator** | Enruta la pregunta (docs/sql/both) + evalúa si el contexto es suficiente (grade) | credencial + modelo del chatbot (rol `evaluator`, o el por defecto) | de pago (NVIDIA free / DeepInfra) |
| **Generación — sql_generator** | Genera la consulta SQL (escenarios sql/mixed) | rol `sql_generator` (o por defecto) | de pago |
| **Generación — answer_generator** | Sintetiza la respuesta final (o abstención) | rol `answer_generator` (o por defecto) | de pago |
| **Juez (RAGAS)** | Puntúa faithfulness / answer_relevancy / context_precision / context_recall | credencial + modelo del **juez** (otra familia) | de pago |
| **Embeddings** | Vectoriza la pregunta para recuperar chunks (retrieval) **y** los usados internamente por RAGAS | **bge-m3 LOCAL (Ollama)** | **gratis** |
| **Juez inline de corrección** | Marca cada respuesta correcta/incorrecta vs `ground_truth` (ayuda de traza en vivo, no es RAGAS) | `gemma3:1b` LOCAL (Ollama) | **gratis** |
| **Métricas deterministas** | routing_accuracy, abstain_accuracy | código, sin modelo | gratis |

**Regla clave:** solo pagas por **generación + juez** (texto). Embeddings y el juez-inline son **locales/gratis**.

## 3. Preparación (una vez, antes de lanzar)
1. **Credencial** (Credenciales → OpenAI-compatible): NVIDIA `https://integrate.api.nvidia.com/v1` + `nvapi-…` (o DeepInfra). Botón **"Probar"** → lista los modelos disponibles = confirmación de que la key y el endpoint valen. Rellena **"Peticiones concurrentes máx."** con el límite del proveedor (NVIDIA ~6, DeepInfra ~16) para que la eval no lo exceda.
2. **Chatbot** *World Countries Bot*: `llm_selection` → esa credencial + modelo de generación (p.ej. `deepseek-ai/deepseek-v4-flash`). (Opcional: modelos distintos por rol.)
3. **Juez** (en el formulario de lanzar eval): misma credencial + un modelo de **otra familia** (p.ej. `qwen/qwen3.5-397b` o `zhipuai/glm-5.1`) para evitar sesgo de auto-preferencia.
4. **Dataset**: *World Countries* (100 preguntas) o la copia *demo 5q* (5) para smoke.

## 4. Al lanzar — flujo POR CADA pregunta (pipeline de generación)
Para cada fila del dataset, el sistema ejecuta `answer_query` (modo router explícito):
1. **route** — el LLM `evaluator` decide la ruta: `docs`, `sql` o `both`. → emite paso `route`.
2. **retrieve** (si la ruta incluye docs) — se **embebe la pregunta con bge-m3 local** y se busca en Qdrant (colección del KB) → top-k chunks.
3. **sql** (si la ruta incluye sql) — el LLM `sql_generator` genera SQL → se ejecuta contra el **MySQL provisionado** del dataset → filas. (Con capas de seguridad: mínimo privilegio + validación AST `sqlglot`.)
4. **grade** — el LLM `evaluator` juzga si el contexto recuperado es suficiente; si no, puede reintentar recuperación (bucle agéntico, hasta `max_retrieval_iterations`).
5. **synthesize** — el LLM `answer_generator` produce la respuesta final citando el contexto; si el contexto es insuficiente y la abstención está activada → **"I don't know: …"**.

→ Cada pregunta respondida se **persiste al instante** en `eval_runs/<run_id>/trace.jsonl` (pregunta, respuesta, contextos, citas, iteraciones, tokens, latencia, y `judged_correct` del juez-inline). En la UI ves **"Pregunta X/N"** con los pasos y tiempos en vivo, y puedes **cancelar**.

## 5. Al terminar la generación — SCORING RAGAS (el juez, en lote)
Para cada pregunta puntuable (no-abstain, con respuesta + contexto), el **modelo juez** calcula:
| Métrica | Qué comprueba | Llamadas al juez |
|---|---|---|
| **faithfulness** | ¿la respuesta está soportada por el contexto? (detecta alucinación) | 2 (descomponer + verificar) |
| **answer_relevancy** | ¿la respuesta responde a la pregunta? | 1 LLM + embeddings (bge-m3) |
| **context_precision** | ¿los chunks recuperados eran útiles? | 1 por chunk (~k) |
| **context_recall** | ¿el `ground_truth` está cubierto por el contexto? | 1 |

→ ~**9 llamadas al juez por pregunta** (por eso el juez es el grueso del coste). Temperatura **0** (reproducible). Detalle de los prompts en `docs/` o en `ragas/metrics/`.

**Deterministas (sin LLM, sin coste):**
- **routing_accuracy**: ¿la ruta elegida coincide con la esperada del escenario? (`doc_only`→docs, `sql_only`→sql, `mixed`→both).
- **abstain_accuracy**: en escenarios `abstain`, ¿se abstuvo correctamente?
- *(execution_accuracy para SQL: hoy es post-proceso manual, no va en el run automático.)*

## 6. Qué obtienes
`eval_runs/<run_id>/report.json` + `report.md` + fila en la BD (`eval_runs`), visibles en la UI (**View Report / View JSON**):
- **Media por métrica** + **desglose por escenario** + fila por pregunta.
- **IC 95% por bootstrap** por métrica (usa `eval-report-stats.py` para generar las tablas de resultados; con n pequeño por escenario los IC salen anchos — la columna `n` lo hace visible).
- **Tokens** (generación in/out + juez in/out), **coste** estimado, **latencia** por pregunta.

## 7. Coste y rate limits
- **NVIDIA free**: $0. Límite **~40 req/min** → concurrencia baja (~4-6) o el juez revienta el límite (429).
- **DeepInfra** (deepseek-v4-flash $0.10/M in, $0.20/M out): 100 preguntas ≈ **<$1** (el juez domina). 200 concurrentes → ~16 va bien.
- Embeddings + juez-inline: **gratis** (local).
- **Auto-ajuste (nuevo):** cada **credencial** tiene un campo opcional **"Peticiones concurrentes máx." (`max_concurrency`)**. Si lo rellenas (p. ej. 6 para NVIDIA, 16 para DeepInfra), la evaluación **dimensiona automáticamente** los workers del juez RAGAS a ese valor — no hace falta acordarse del env `RAGAS_MAX_WORKERS`. Vacío = usa `RAGAS_MAX_WORKERS`/16.

## 8. Garantías (no se pierde nada)
- `trace.jsonl` se escribe **por pregunta** (append) → si algo peta, las respuestas ya generadas están en disco.
- El juez RAGAS **reintenta** (10× con backoff); fallos por-métrica se toleran (el informe se construye igual).
- Vista en vivo + **cancelar** → informe parcial válido.

## 9. Checklist antes de poner la API de pago
- [ ] Credencial creada y **"Probar"** lista modelos.
- [ ] Chatbot → credencial + modelo de generación; **juez** → credencial + modelo de otra familia.
- [ ] `max_concurrency` de la credencial puesto al rate limit del proveedor (o `RAGAS_MAX_WORKERS` como alternativa).
- [ ] **Smoke con el dataset de 5** → informe se renderiza + coste ≈ céntimos + métricas con sentido.
- [ ] Revisar el informe de 5: ¿routing_accuracy correcto? ¿faithfulness/relevancy razonables? ¿abstención bien?
- [ ] Solo entonces: lanzar las **100** (primero con NVIDIA free; DeepInfra si hace falta más throughput).
