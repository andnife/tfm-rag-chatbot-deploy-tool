# World Countries — dataset de estrés (patas cojas)

Dataset **focalizado** para poner a prueba únicamente los tres modos de fallo que
destapó el run completo de 180 preguntas (análisis de errores). No pretende ser
representativo: **casi todas las preguntas atacan una
debilidad concreta** para medir el efecto de los arreglos con señal limpia.

18 preguntas: 12 `sql_only` + 4 `mixed` + 1 `doc_only` (control) + 1 `abstain`
(control).

## Dataset paralelo y autocontenido

Es un dataset **independiente** del `world-countries` original (que sigue
existiendo sin cambios). Trae sus **propios** `docs/` (los 10 artículos completos)
y `seed.sql` (BD completa, 40 países) — idénticos a los del original — para poder
crearlo por separado. Lo único reducido son las **preguntas** (18 focalizadas en
los fallos), no los documentos ni la base de datos. Al crearlo en el panel:

1. Sube los `docs/*.txt` de **este** directorio.
2. Pega **este** `seed.sql` como semilla SQL.
3. Importa **este** `rows.jsonl`.
4. Lánzalo contra el **mismo chatbot** (World Countries Bot) que el run de 180.

Datos de referencia (semilla actual): 40 países — Europa 13, Asia 10, América 9,
África 6, Oceanía 2; 7 países con moneda `Euro`; 7 con lengua oficial `Español`.
Todas las `sql_reference` se han ejecutado contra la BD y devuelven el
`ground_truth` indicado.

## Qué pata prueba cada bloque

### Pata A — Sobre-abstención en SQL (grader) · filas 1-7
`sql_only` cuya respuesta es un **escalar / conteo / valor único** (`COUNT(*)`,
`MAX`, `ORDER BY … LIMIT 1`, lookup). En el run de 180 el sistema **ejecutaba la
query, obtenía el resultado y aun así abstenía** ("no tengo información
suficiente") porque el grader estricto rechazaba el resultado escueto.
- **Antes del fix:** muchas de estas abstienen pese a tener el dato → RAGAS ≈ 0.
- **Después del fix (grader consciente de ruta):** deberían responder con el valor
  → faithfulness/answer_relevancy altos.

### Pata C — Filtro categórico con valores en español · filas 8-12
`sql_only` que **filtran por columnas de texto** (`continent`, `currency`,
`official_language`) cuyos valores están en español y **con acentos**
(`'Europa'`, `'África'`, `'América'`, `'Oceanía'`, `'Español'`). El generador de
8B tiende a inventar el valor en inglés (`'Europe'`) → 0 filas → falla. (De hecho,
hasta un cliente MySQL con charset incorrecto falla el match por el acento — la
fragilidad es real.)
- Estas seguirán fallando **hasta** que se implemente el fix pendiente de incluir
  los **valores distintos** de columnas categóricas en el esquema que ve el
  generador. Sirven para **medir** esa pata y validar ese arreglo cuando llegue.

### Pata B — Enrutado de preguntas compuestas (`both`) · filas 13-16
`mixed`: cada pregunta tiene **dos partes explícitas**, una de documento
("según el artículo…") y otra de base de datos ("según la base de datos…"). En el
run de 180 solo 2/40 se enrutaron a `both` (routing_accuracy 0.05).
- **Antes del fix:** enrutan a una sola herramienta → responden media pregunta →
  routing_accuracy 0.
- **Después del fix (guía de `both` en el router):** deberían enrutar a `both` →
  routing_accuracy sube y responden ambas partes.

### Controles · filas 17-18
- `doc_only` (capital de España) y `abstain` (inflación de Japón, no responible).
  Sirven de **línea base**: deben seguir saliendo bien (doc) y abstenerse
  correctamente (abstain) tras los cambios; si se rompen, los fixes causaron
  regresión.

## Cómo interpretar el resultado

Compara el desglose **por escenario** con el del run de 180 (misma configuración
de modelos). El objetivo no es la media global, sino ver el **delta** en:
- `sql_only`: ¿sube faithfulness/answer_relevancy? (pata A resuelta).
- `mixed`: ¿sube `routing_accuracy` desde ~0.05? (pata B resuelta).
- Las filas 8-12 concretas: ¿siguen fallando? (pata C, pendiente de su fix).

> Metodología: este dataset materializa la evaluación como
> **bucle de mejora** — mismas preguntas antes/después de cada arreglo para aislar
> su efecto, en lugar de una única foto agregada.
