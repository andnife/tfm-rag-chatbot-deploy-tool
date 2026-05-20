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

(Aún ninguna. Las irán añadiendo los subagents al ejecutar el plan.)
