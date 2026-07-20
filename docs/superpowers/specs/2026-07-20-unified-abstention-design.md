# Diseño: abstención unificada (una sola generación LLM, en español, con contexto por causa)

Fecha: 2026-07-20
Estado: aprobado el diseño; pendiente spec-review + implementación TDD.

## Problema

El chatbot RAG se abstiene ("no tengo la información") por **tres vías distintas**, cada
una con comportamiento y mensaje diferentes, y dos de ellas en **inglés fijo**:

1. **Grader (rutas `docs`/`both`)** — `application/chat/answer_query.py:407-416`.
   Produce `"I don't know: " + <razón del grader>` o el fallback fijo
   `"I don't know: The available knowledge did not contain enough to answer."`
   (sub-caso: fallo de parseo del grader → `"I don't know: grader returned no valid verdict"`,
   `application/chat/grade.py:107`).
2. **SQL sin datos (ruta `sql`)** — mismo bloque, con `verdicts` vacío → fallback inglés fijo.
   La sub-ruta SQL no tiene grader; la insuficiencia = `not bool(sql_contexts)`.
3. **Auto-rechazo en síntesis** — `application/chat/synthesize.py:28-29` (`_DOCS_SYSTEM`):
   *"If the answer isn't in the provided material, say you don't have that information."*
   El generador emite texto libre (normalmente en español) y **no pasa** por el chokepoint
   de abstención; es indistinguible de una respuesta normal a nivel de orquestador.

Resultado: mensajes incoherentes y en idiomas distintos. Objetivo: **una sola generación
de abstención por LLM, en el idioma de la conversación (el configurado en el bot vía su
`system_prompt` o el que use el usuario en su pregunta — NO fijado a español), con la
persona del bot, y con el contexto correcto de por qué se abstuvo** (cada vía aporta su
causa). Misma regla de idioma que ya usa la síntesis normal (`_DOCS_SYSTEM`: "in the same
language as the question").

## No-objetivos

- No cambiar el routing, el grader ni la sub-ruta SQL.
- No cambiar la semántica del gate `pipeline.abstain_when_insufficient`.
- No tocar la evaluación: su detección de abstención ya es **semántica** (juez LLM,
  `infrastructure/evaluation/ragas_evaluator.py:65-74`) con heurístico de respaldo que
  **ya cubre español** (`_ABSTAIN_ANSWER_HINTS`, `:59-63`). Un mensaje español correcto
  sigue contando como abstención → `abstain_accuracy` intacto.

## Diseño

### 1. Módulo nuevo: `application/chat/abstain.py`

Función única de generación:

```python
class AbstainCause(str, Enum):
    DOCS_INSUFFICIENT = "docs_insufficient"
    SQL_NO_DATA        = "sql_no_data"
    BOTH_INSUFFICIENT  = "both_insufficient"
    SYNTHESIS_DECLINED = "synthesis_declined"

# Contexto interno por causa (en inglés como el resto de prompts del código; es
# CONTEXTO para el modelo, NO el texto de salida — el idioma de salida lo fija la
# instrucción "same language as the question" + la persona del bot).
_CAUSE_CONTEXT: dict[AbstainCause, str] = {
    DOCS_INSUFFICIENT: "The knowledge-base documents do not contain the requested information.",
    SQL_NO_DATA:       "The database query returned no results for what was asked.",
    BOTH_INSUFFICIENT: "Neither the documents nor the database contain the requested information.",
    SYNTHESIS_DECLINED:"The retrieved information is not enough to answer the question confidently.",
}

_ABSTAIN_SYSTEM = (
    "The system could not find the information needed to answer. Write ONE short, "
    "polite, honest reply, IN THE SAME LANGUAGE AS THE USER'S QUESTION, stating that "
    "you don't have that information. Do not invent data or cite sources; if natural, "
    "suggest rephrasing or another channel. Follow the assistant persona above for tone."
)

async def generate_abstention(*, llm, base_url, api_key, model_id, generation,
                              system_prompt, user_message,
                              cause: AbstainCause, detail: str | None = None) -> str
```

- Compone: `f"{system_prompt}\n\n{_ABSTAIN_SYSTEM}\n\nContexto: {_CAUSE_CONTEXT[cause]}"`
  (+ `Detalle: {detail}` si viene del grader), y un mensaje `user` con la pregunta.
- Usa el **answer_generator** (`ans_sel`) — es la "voz" del bot.
- Reutiliza `_text_of` (extraer del `LLMResponse`).

### 2. Chokepoint (Paths 1 y 2): `answer_query.py:405-418`

Sustituir el string fijo por una llamada a `generate_abstention`, derivando la causa:

```
if route == ROUTE_DOCS  → DOCS_INSUFFICIENT   (detail = verdicts[-1].abstain_reason si existe)
if route == ROUTE_SQL   → SQL_NO_DATA
if route == ROUTE_BOTH  → BOTH_INSUFFICIENT
```

`citations = []`, `await _emit("synthesize", chars=..., abstained=True)`.
Se abre `ans_sel` para esta llamada (antes solo se abría en el `else`).

### 3. Path 3 (centinela + detección) — preserva la red anti-alucinación

- En `synthesize.py`: definir `NO_INFO_SENTINEL = "__NO_INFO__"` (exportado).
  Cambiar la instrucción de `_DOCS_SYSTEM`:
  *"If the answer isn't in the provided material, reply with EXACTLY `__NO_INFO__`
  and nothing else."*
  Se **mantiene** `_SQL_ANSWER_SYSTEM` (nunca abstenerse con datos SQL presentes),
  así el centinela no se dispara cuando hay resultado SQL.
- En `answer_query.py`, tras `synthesize_answer` (rama `else`): si
  `NO_INFO_SENTINEL in assistant_content` → llamar `generate_abstention(cause=SYNTHESIS_DECLINED)`,
  vaciar `citations`, `_emit(..., abstained=True)`. Detección determinista (substring).
- `ROUTE_NORMAL` usa `_NORMAL_SYSTEM` (sin centinela) → nunca dispara Path 3.

## Riesgos y mitigación

- **Cambiar `_DOCS_SYSTEM` afecta a TODAS las respuestas documentales** (incluidas las 9
  preguntas buenas de la demo). Un falso centinela convertiría una buena respuesta en
  abstención. Mitigación: **regresión obligatoria** con `scripts/demo-smoke.sh` (9 buenas
  siguen respondiendo con 5 citas + 3 controles abstienen en español limpio) antes de
  aceptar el cambio. Modelo de demo (Qwen2.5-72B) sigue instrucciones con fiabilidad.
- **La llamada de abstención podría, en teoría, "responder" en vez de abstenerse.** El
  prompt lo prohíbe explícitamente; con modelo capaz el riesgo es bajo y la eval lo
  detectaría igualmente por vía semántica.
- **Coste/latencia:** +1 llamada LLM (~1-3 s) **solo al abstenerse**. Las respuestas
  normales no cambian.

## Plan de pruebas (TDD)

Unit (mismo patrón `_FakeLLM` que `tests/unit/test_synthesize.py`):
1. `test_abstain.py`: `generate_abstention` compone el system con el contexto de cada
   causa, pasa la pregunta como `user`, devuelve el texto del LLM, incluye `detail`.
2. `synthesize.py`: `_DOCS_SYSTEM` contiene la instrucción del centinela; con SQL presente
   se mantiene el override; `NO_INFO_SENTINEL` exportado.
3. `answer_query` (integración con fakes): 
   - ruta docs insuficiente → mensaje unificado (llama a `generate_abstention` con
     `DOCS_INSUFFICIENT`), sin citas.
   - ruta sql sin datos → `SQL_NO_DATA`.
   - ruta docs suficiente pero síntesis emite `__NO_INFO__` → `SYNTHESIS_DECLINED`, sin citas.
   - ruta docs suficiente y síntesis normal → respuesta con citas (sin regresión).
4. Suite unit completa verde + ruff + mypy.

Regresión funcional end-to-end: `bash scripts/demo-smoke.sh` sobre `demo@fake.com`.

## Alcance de archivos

- NUEVO: `backend/src/tfm_rag/application/chat/abstain.py`
- EDIT: `backend/src/tfm_rag/application/chat/synthesize.py` (centinela + `_DOCS_SYSTEM`)
- EDIT: `backend/src/tfm_rag/application/chat/answer_query.py` (chokepoint + detección Path 3)
- NUEVO: `backend/tests/unit/test_abstain.py` (+ ampliar `test_synthesize.py`, tests de answer_query)
