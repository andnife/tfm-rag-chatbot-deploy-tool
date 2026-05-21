# Subagent Questions Log

Documento vivo en el que **cada subagent implementer / reviewer** registra dudas, incertidumbres o decisiones que necesitan confirmación del usuario humano.

## Cómo usarlo (instrucciones para subagents)

Si durante tu tarea encuentras:
- Una ambigüedad en el plan o spec que no puedas resolver sin asumir.
- Una decisión técnica con dos o más caminos válidos y no obvio cuál preferir.
- Un detalle del entorno/host (versión de OS, herramientas locales) que afecta a tu implementación.
- Un riesgo o concern que el plan no contempla.

→ **NO bloquees**. Si puedes seguir con una asunción razonable, hazlo, y **añade una entrada aquí** con:
- Plan + Tarea + Step
- Pregunta concreta (1-2 frases)
- Asunción aplicada (qué hiciste mientras tanto)
- Impacto si la asunción es errónea

El usuario revisará este doc periódicamente y responderá. Las respuestas se aplican retroactivamente en una iteración posterior si hace falta.

## Formato de entrada

```
### YYYY-MM-DD HH:MM — Plan-NN / Task-N / Step-N.N — <título breve>

**Subagent role:** implementer | spec-reviewer | code-quality-reviewer
**Pregunta:** ...
**Asunción aplicada:** ...
**Impacto si es errónea:** bajo | medio | alto
**Respuesta del usuario:** (vacío hasta que conteste)
```

---

## Entradas

### 2026-05-20 — Plan-01 / Task 2 / Step 2.1 — Spec includes unused `import os` in test file

**Subagent role:** implementer (Task 2)
**Pregunta:** El spec del test incluía `import os` que nunca se usa. Ruff con rule F401 lo rechazaría. ¿Mantenemos el import (y desactivamos F401 para ese archivo) o lo quitamos del spec?
**Asunción aplicada:** Quitado el import (la alternativa habría dejado fallar el lint, lo cual no es aceptable).
**Impacto si es errónea:** Bajo — solo cosmético.
**Respuesta del usuario:** ✅ Aceptada (2026-05-21, sesión 6). Quitar el import es lo correcto: no compensa silenciar reglas de lint por un import muerto. Pauta para subagents futuros: si un spec contiene código que no se usa, recórtalo antes de copiarlo.

---

### 2026-05-20 — Plan-01 / Task 3 / Step 3.6 — Docker unavailable in WSL environment

**Subagent role:** implementer (Task 3)
**Pregunta:** Docker no está disponible en este entorno WSL2 (comando no encontrado). ¿Procedo con verificación de imports y salto la ejecución del contenedor Postgres?
**Asunción aplicada:** Saltado `docker run`. Verificé que todos los imports funcionan correctamente (`from tfm_rag.infrastructure.persistence.engine import build_engine, build_session_factory, session_scope; from tfm_rag.infrastructure.persistence.base import Base` → OK). El test está correctamente marcado con `@pytest.mark.integration` y se deselecciona cuando se filtra con `-m "not integration"`. La integración completa con Postgres será validada en Task 7 cuando docker-compose esté arriba.
**Impacto si es errónea:** Bajo — el código está bien tipado y es importable. La verdadera prueba de conectividad (conexión a Postgres real) ocurrirá en Task 7 con docker-compose. Si hay un error en engine.py, se detectará cuando la sesión intente conectar.
**Respuesta del usuario:** ✅ Aceptada (2026-05-21, sesión 6). El usuario está activando Docker Desktop / WSL2 ahora; los integration tests deferidos se ejecutarán en sesión 6 antes de cerrar plan #7.

---

### 2026-05-20 — Plan-01 / Task 4 / Step 4.6 — Docker unavailable in WSL; full `alembic upgrade head` test deferred

**Subagent role:** implementer (Task 4)
**Pregunta:** Task 4.6 requiere ejecutar `alembic upgrade head` contra una base de datos Postgres real. Docker no está disponible en este entorno WSL2. ¿Debo diferir la ejecución completa del test a Task 7/9 cuando docker-compose esté levantado?
**Asunción aplicada:** Sí. En su lugar, ejecuté verificaciones estructurales sin DB: `alembic heads` (verifica que la migración es bien formada) → OK; `alembic history` (muestra cadena de migraciones) → OK; importlib check (verifica que 0001_baseline.py es importable y revision="0001") → OK. El archivo `test_alembic_baseline.py` existe y está correctamente escrito con `@pytest.mark.integration`, se deseleccionará sin Docker. La ejecución real (conexión a Postgres + upgrade + lectura de alembic_version) ocurrirá en Task 7 o Task 9.
**Impacto si es errónea:** Bajo — la estructura de migración Alembic y la sintaxis de env.py han sido validadas sin DB. La verdadera prueba de integración con Postgres se ejecutará cuando el contenedor esté disponible. Si hay errores en los imports de env.py (Base, get_settings), se detectarían en Task 7.
**Respuesta del usuario:** ✅ Aceptada (2026-05-21, sesión 6). Verificación real diferida a sesión 6 cuando Docker esté operativo — antes de añadir plan #7 corremos `alembic upgrade head` y los integration tests acumulados de M1.

---

### 2026-05-21 — Plan-07 / Task-4 / Step-4.12 — `test_source_connection` collected by pytest as a test

**Subagent role:** implementer (Task 4)
**Pregunta:** The test file (`test_knowledge_use_cases.py`) imports `test_source_connection` from the use case module. Because the name starts with `test_`, pytest collects it as an additional test item (13 collected vs expected 12), causing `1 error` for missing fixtures `spec_type`/`spec`. The plan expects exactly 12 PASSED.
**Asunción aplicada:** Added `__test__ = False` at module level in `test_source_connection.py` (the use case file, not the test file). This is a standard pytest mechanism to suppress test collection from a non-test module. The use case logic is unchanged.
**Impacto si es errónea:** Bajo — `__test__ = False` is purely a pytest directive and has no effect on runtime behaviour of the use case. If the plan author prefers a different fix (e.g., renaming the import in the test file), the one-liner can be removed.
**Respuesta del usuario:** ✅ Aceptada (2026-05-21, sesión 6). Hack mínimo y aislado al archivo del use case; el código del runtime no cambia. La alternativa (import-renombrar en el test file con `as run_test_source_connection`) era equivalente. Pauta para subagents futuros: si un use case se llama `test_*` (porque el spec dice `TestX`), `func.__test__ = False` es el patrón aceptado en este repo. Plan #6 no tuvo el problema porque su `test_credential` solo se importa desde el router (no desde tests).

---

### 2026-05-21 — Plan-07 / Task-6 / Step-6.1 — Integration test file needed `_session_factory` reset to fix cross-loop event loop clash

**Subagent role:** implementer (Tasks 5-6)
**Pregunta:** The verbatim test file from the plan caused the second test (`test_kb_isolation_between_tenants`) to fail with `RuntimeError: Task ... got Future ... attached to a different loop`. Root cause: `_session_factory` in `dependencies.py` is a module-level global set lazily on first use. With `asyncio_mode=auto` (per-function event loop), the first test sets `_session_factory` tied to loop-1; the second test runs in loop-2 but tries to reuse the same factory with connections from loop-1.
**Asunción aplicada:** Added `_deps._session_factory = None` at the top of the `_clean_kb_tables` fixture (the fixture already used by both tests). This forces a fresh factory per test. The import was added: `import tfm_rag.infrastructure.api.dependencies as _deps`. No other changes to the verbatim test file from the plan.
**Impacto si es errónea:** Bajo — the reset is purely a test harness concern, not a production code change. If the pattern is rejected, the alternative is to set `asyncio_default_test_loop_scope=session` in `pytest.ini` (one shared event loop for all integration tests), but that changes the existing test isolation model. The per-test reset is the narrower fix.
**Respuesta del usuario:** ✅ Aceptada (2026-05-21, sesión 6). Bug real del harness, no del use case. Pauta para futuros tests de routers que dependan de la fábrica global de sesiones: reset `_deps._session_factory = None` en la fixture de limpieza. Nota arquitectónica para una sesión futura: el `_session_factory` global en `infrastructure/api/dependencies.py` está bien para producción (un solo event loop por proceso uvicorn) pero acopla los tests al primer event loop. Una refactor candidata es moverlo al lifespan de FastAPI (`app.state.session_factory`) — fuera de scope ahora; abrir cuando toque #plan-10 si la necesidad reaparece.
