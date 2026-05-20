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
**Respuesta del usuario:** (pendiente)

---

### 2026-05-20 — Plan-01 / Task 3 / Step 3.6 — Docker unavailable in WSL environment

**Subagent role:** implementer (Task 3)
**Pregunta:** Docker no está disponible en este entorno WSL2 (comando no encontrado). ¿Procedo con verificación de imports y salto la ejecución del contenedor Postgres?
**Asunción aplicada:** Saltado `docker run`. Verificé que todos los imports funcionan correctamente (`from tfm_rag.infrastructure.persistence.engine import build_engine, build_session_factory, session_scope; from tfm_rag.infrastructure.persistence.base import Base` → OK). El test está correctamente marcado con `@pytest.mark.integration` y se deselecciona cuando se filtra con `-m "not integration"`. La integración completa con Postgres será validada en Task 7 cuando docker-compose esté arriba.
**Impacto si es errónea:** Bajo — el código está bien tipado y es importable. La verdadera prueba de conectividad (conexión a Postgres real) ocurrirá en Task 7 con docker-compose. Si hay un error en engine.py, se detectará cuando la sesión intente conectar.
**Respuesta del usuario:** (pendiente)

---

### 2026-05-20 — Plan-01 / Task 4 / Step 4.6 — Docker unavailable in WSL; full `alembic upgrade head` test deferred

**Subagent role:** implementer (Task 4)
**Pregunta:** Task 4.6 requiere ejecutar `alembic upgrade head` contra una base de datos Postgres real. Docker no está disponible en este entorno WSL2. ¿Debo diferir la ejecución completa del test a Task 7/9 cuando docker-compose esté levantado?
**Asunción aplicada:** Sí. En su lugar, ejecuté verificaciones estructurales sin DB: `alembic heads` (verifica que la migración es bien formada) → OK; `alembic history` (muestra cadena de migraciones) → OK; importlib check (verifica que 0001_baseline.py es importable y revision="0001") → OK. El archivo `test_alembic_baseline.py` existe y está correctamente escrito con `@pytest.mark.integration`, se deseleccionará sin Docker. La ejecución real (conexión a Postgres + upgrade + lectura de alembic_version) ocurrirá en Task 7 o Task 9.
**Impacto si es errónea:** Bajo — la estructura de migración Alembic y la sintaxis de env.py han sido validadas sin DB. La verdadera prueba de integración con Postgres se ejecutará cuando el contenedor esté disponible. Si hay errores en los imports de env.py (Base, get_settings), se detectarían en Task 7.
**Respuesta del usuario:** (pendiente)
