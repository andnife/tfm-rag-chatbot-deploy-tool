# Preguntas pendientes para el usuario

**Estado:** ✅ TODAS RESPONDIDAS (2026-05-20). Las decisiones se aplicaron al HTML, log y handover. Este documento se conserva como registro de las preguntas y respuestas.

**Resumen de aplicaciones:**
- P-01 → roadmap sin estimaciones temporales; prioridades M1–M4 esencial, M6 crítico, M5 visible, M7 opcional.
- P-02 → Qdrant: colección por `(tenant, dim)`.
- P-03 → Next.js + NextAuth + shadcn.
- P-04 → Preact (sin cambios).
- P-05 → dataset público preferente; build propio en M6 si no encaja ninguno.
- P-06 → Ollama default + servicio obligatorio en docker-compose con seed de modelos.
- P-07 → SSE de iteraciones del loop (iteration_start, tool_call, tool_result, generating, final_answer, done); respuesta final no streamea token-a-token.
- P-08 → JWT 24h sin refresh.
- P-09 → tema neutro shadcn slate.
- P-10 → solo local con docker-compose.

---

Documento original (contexto + pregunta + opciones + recomendación + respuesta del usuario):

---

## P-01 — Calendario del TFM vs roadmap propuesto

**Contexto.** La memoria del TFM (PDF) fija el "Calendario de implementación: 05/05/2026 – 06/07/2026 (~9 semanas)". Mi roadmap M1–M7 estima ~14 semanas (2 sem/hito × 7 hitos) para un dev solo + asistente de IA. Hay un desfase de ~5 semanas.

**Pregunta:** ¿Cómo encajamos el roadmap en el calendario académico?

**Opciones:**

- **A)** Comprimir a 9 semanas reduciendo scope del MVP (típicamente: cortar M6 reranker + M7 hardening; dejar evaluación mínima sin matriz de variantes).
- **B)** Comprimir a 9 semanas paralelizando frontend/backend y delegando más boilerplate al agente (asume riesgo alto de no terminar M5–M7).
- **C)** Mantener M1–M7 completos y aceptar que el calendario académico solo cubre M1–M4 (lo demás post-entrega).
- **D)** Re-estimar conmigo cada hito en horas con tu disponibilidad real (ahora mismo asumo "dev solo focalizado", que puede no ser tu caso).

**Mi recomendación:** **A**. Para la entrega académica, M1–M5 (plataforma + KB doc + chatbot básico + SQL + widget) demuestran lo esencial; reranker + RAGAS + hardening se pueden listar como "trabajo realizado tras la entrega" en la memoria. M6 puede reducirse a "evaluación con configuración base" sin matriz comparativa.

**Impacto si responde tarde:** Alto. Define qué CAPs entran en proposals y en qué orden.

**Respuesta:** Yo creo que tu estimacion probablemente sea demasiado elevada, con agentes de programacion se programa muy rapido y no creo que nos lleve tanto tiempo, ademas de eso, tendre que obtener metricas de los sistemas RAG y demas (no se si has contado con esa parte del TFM), no hagas un roadmap "temporal" los tiempos van a no ser reales casi nunca, simplemente centremonos en las funcionalidades. Si te quedas mas tranquilo, obviamente priorizaremos lo mas primordial para el trabajo antes de pasar a desarrollar cosas del MVP que pueden ser mas irrelevantes.

---

## P-02 — Qdrant: ¿colección por tenant o por (tenant, dim)?

**Contexto.** Cada KB puede tener su propio `embedding_selection` con un `dim` distinto (e.g. bge-m3=1024, text-embedding-3-small=1536). Qdrant por defecto exige que **todos los puntos de una colección tengan el mismo `dim`**. Tengo dos formas de modelarlo:

- **Una colección por tenant** + restricción "todas las KBs del tenant deben usar el mismo embedding_selection" (más fuerte que la regla actual, que solo restringe entre KBs adjuntas al mismo chatbot).
- **Una colección por (tenant, dim)** — el tenant tiene N colecciones, una por cada embedding model que use.

Qdrant también soporta "named vectors" en una misma colección, pero rompe la simplicidad del filtro.

**Pregunta:** ¿Qué modelo prefieres?

**Opciones:**

- **A)** Una colección por tenant. **Trade-off:** restringe a un solo embedding por tenant (en un mismo tenant todas las KBs comparten modelo). Sencillo de operar.
- **B)** Una colección por `(tenant, dim)`. **Trade-off:** permite múltiples embeddings en un tenant, pero el modelo de §9 cambia: `tenant.qdrant_collection` deja de ser un campo único y pasa a ser derivable como `kb_chunks__<tenant_id>__<dim>`.
- **C)** Una colección por tenant con named vectors (vectores con nombre por modelo). **Trade-off:** más complejo de operar, requiere migración del schema Qdrant al añadir embedding nuevo.

**Mi recomendación:** **B**. Es ligeramente más complejo pero alinea con el principio de §6 de que "una KB fija su embedding" y no obliga al usuario a re-indexar todo si decide probar otro modelo.

**Impacto si responde tarde:** Alto. Cambia §9 (modelo de datos) y §12 (invariantes de aislamiento).

**Respuesta:** Lo que consideres, B esta bien si lo crees.

---

## P-03 — Stack del panel frontend

**Contexto.** El PDF del TFM menciona "Next.js" como parte del stack. En el log de la sesión 1, NextAuth aparece como recomendación para Google OAuth. He propuesto en §10 **React 18 + Vite + TanStack Query + Zustand + Tailwind + shadcn/ui**, sin Next.js, porque (a) no necesitamos SSR para un panel autenticado, (b) Vite tiene DX más rápida en desarrollo, (c) shadcn da componentes accesibles out-of-the-box.

**Pregunta:** ¿Mantengo React+Vite o vuelvo a Next.js como en el PDF?

**Opciones:**

- **A)** React 18 + Vite + TanStack + Zustand + shadcn (lo que tengo en §10). Google OAuth se hace con `@react-oauth/google` en cliente, callback al backend.
- **B)** Next.js (App Router) + NextAuth + shadcn. Se alinea con el PDF; NextAuth simplifica Google OAuth. SSR no se usa pero está disponible.
- **C)** Next.js + shadcn pero sin NextAuth (gestionando JWT y OAuth manualmente como en A).

**Mi recomendación:** **B** si la memoria del TFM ya menciona Next.js y NextAuth como compromiso. **A** si tienes libertad. La A es más simple para un dev solo; la B es más alineada con la entrega académica.

**Impacto si responde tarde:** Alto si se cambia post-M1 (reescritura del panel). Bajo si se decide ahora.

**Respuesta:** B, no podemos desalinearnos del TFM.

---

## P-04 — Framework del widget JS

**Contexto.** Tengo dos referencias contradictorias: el log de la sesión 1 dice "Widget JS independiente (vanilla TS)" como decisión cerrada; en §11 yo he propuesto **Preact + signals + Tailwind con prefijo `tfm-`**. Preact es más cómodo de desarrollar pero añade ~4 KB; vanilla TS deja el bundle más pequeño y sin framework.

**Pregunta:** ¿Vanilla TS o Preact?

**Opciones:**

- **A)** Preact + signals (~4 KB framework + tu código). Bundle objetivo &lt;100 KB gzipped. Desarrollo cómodo, components reactivos, fácil de mantener.
- **B)** Vanilla TS (sin framework). Bundle más pequeño (~30-50 KB). Requiere escribir manejo de DOM a mano y un state tiny.
- **C)** Lit (Web Components nativos). Standard, sin framework custom, ~5 KB. Encaja bien con Shadow DOM.

**Mi recomendación:** **A** (Preact) si priorizas velocidad de desarrollo, **C** (Lit) si priorizas estándares y reuso. Vanilla TS no merece el esfuerzo extra en MVP.

**Impacto si responde tarde:** Medio (rewrite del widget si se cambia, pero el widget es un módulo aislado).

**Respuesta:** A

---

## P-05 — Dataset RAGAS del TFM

**Contexto.** §13 propone 4 escenarios (`doc_only`, `sql_only`, `mixed`, `abstain`) y un dataset JSONL con ~50 preguntas. La memoria del TFM ya describe los escenarios (Context Precision/Recall, Faithfulness, Answer Relevancy sobre 3 escenarios). No sé si ya tienes datasets construidos.

**Pregunta:** ¿Ya tienes preguntas + ground truth para los escenarios, o se construyen en M6?

**Opciones:**

- **A)** Ya tengo dataset. Lo guardo en `datasets/` y lo referencia §13. Dime ruta/tamaño/origen.
- **B)** No, hay que construirlo. M6 incluye 50 preguntas/escenario (200 total) generadas con LLM y revisadas manualmente.
- **C)** Reutilizar un dataset público (e.g. RAG-12000, MS MARCO) en lugar de construir uno propio.

**Mi recomendación:** **B**. Construir un dataset propio sobre los PDFs del TFM y una BD demo (chinook) es más relevante académicamente que reutilizar uno público.

**Impacto si responde tarde:** Bajo. Solo afecta el contenido de M6.

**Respuesta:** No tenemos, pensaba buscar algun dataset que existiera ya para la tarea (uno publico como dices) asiqu eC o B si lo creamos como dice. No recuerdo bien que se establecia en el TFM, pero si, alguno de esos será.

---

## P-06 — Ollama como dependencia por defecto

**Contexto.** §6 decidió "BootstrapTenant crea un ProviderCredential Ollama default (config_source=SERVER_ENV)" automáticamente al registrar un usuario. Esto significa que el usuario, al registrarse, ya tiene Ollama disponible — pero implica que el deploy del backend tiene que tener Ollama corriendo (en local o en otro contenedor).

**Pregunta:** ¿Mantenemos Ollama como default obligatorio o lo hacemos opt-in?

**Opciones:**

- **A)** Ollama default obligatorio (lo que tenemos). El usuario nuevo puede crear un chatbot sin configurar nada; el deploy debe tener Ollama. `docker-compose.yml` incluye Ollama como servicio.
- **B)** Ollama opt-in. El usuario nuevo no tiene ningún credential default; debe ir a `/settings/integraciones` y configurar uno (OpenAI, Groq, Ollama, …) antes de poder crear un chatbot. `docker-compose.yml` incluye Ollama solo en perfil `dev`.
- **C)** Ollama default sólo si la variable `OLLAMA_BASE_URL` está definida en el `.env`. Si no, el usuario nuevo no tiene credentials.

**Mi recomendación:** **A** para la entrega del TFM (demo más rápida sin configuración). **C** para una versión más limpia de producción.

**Impacto si responde tarde:** Bajo. Solo afecta `BootstrapTenant` y el README de deploy.

**Respuesta:** A, pero claro necesitaremos que lanzar el backend ejecute ollama localmente tambien (quede configurado automaticamente tambien)

---

## P-07 — Streaming de respuestas en el chat

**Contexto.** §1 y §11 dicen "sin streaming en MVP, respuesta completa por request". El loop agéntico puede tardar 5-15s en respuestas complejas; sin streaming, el usuario ve un spinner durante todo ese tiempo. Con streaming (SSE o WebSocket) verá tokens fluyendo en cuanto el LLM empiece a generar el `final_answer`.

**Pregunta:** ¿Incluimos streaming en el MVP?

**Opciones:**

- **A)** Sin streaming en MVP (lo que tengo). UX más simple, backend más simple. Loading bubble.
- **B)** Streaming con SSE en `/api/chatbots/{id}/chat` y `/api/public/chatbots/{id}/chat`. Cliente y widget muestran tokens en vivo cuando el loop entra en `final_answer`. Las decisiones intermedias del loop (iteraciones de tool) se transmiten como eventos también.
- **C)** Híbrido: sin streaming en widget público (más estable a través de la red del cliente final), con streaming en el playground (UX de desarrollo).

**Mi recomendación:** **A** para no inflar el MVP. **C** si quieres un golpe de efecto en el playground sin complicar el widget.

**Impacto si responde tarde:** Medio. Añadir streaming después requiere tocar la API, el frontend y el widget.

**Respuesta:** Debería haber streaming, o por lo menos una conexión que muestre que el agente está pensando o el proceso realizandose (consultando base de informacion... generando respuesta...) que no sea completamente invisible al usuario. Lo que es el mensaje que recibe al final si que puede ser sin streaming. Pero los procesos intermedios del agente su "pensamiento" si que debe ser visualizado en el momento.

---

## P-08 — Sesión JWT corta sin refresh tokens

**Contexto.** §1 y §12 dicen "JWT corto (1h) sin revocación BD ni refresh tokens. Re-login ante 401". Esto significa que cada hora el usuario tendrá que volver a meter sus credenciales. UX malo para uso real; aceptable para demo académica.

**Pregunta:** ¿Mantenemos JWT 1h sin refresh o añadimos refresh tokens?

**Opciones:**

- **A)** JWT 1h sin refresh (lo que tengo). Aceptable para demo del TFM. Documentado como limitación.
- **B)** JWT corto (15min) + refresh token (30 días) almacenado HttpOnly. Endpoint `POST /api/auth/refresh`. Añade complejidad pero da UX normal.
- **C)** JWT más largo (24h o 7d). Sin refresh. Compromiso entre seguridad y UX.

**Mi recomendación:** **C** (JWT 24h) para la entrega académica. Simpler que **B** y mejor UX que **A**.

**Impacto si responde tarde:** Bajo. Cambiar TTL es un parámetro; añadir refresh tokens es trabajo de un día.

**Respuesta:** Vale, pues C, lo que consideres, si.

---

## P-09 — Branding / tema visual del panel

**Contexto.** §10 dice "tema neutro shadcn slate" sin más. Si la plataforma tiene una identidad (logo, paleta, tipografía), esto se diseña en M5 normalmente.

**Pregunta:** ¿Tienes nombre/marca/paleta para la plataforma?

**Opciones:**

- **A)** Sí — me das logo SVG + paleta hexadecimal + tipografía y los incorporo en `tailwind.config.ts`.
- **B)** No, tema neutro shadcn slate por defecto. La memoria del TFM no exige branding propio.
- **C)** Quiero algo simple sin diseñarlo en detalle: dame 2-3 paletas para elegir.

**Mi recomendación:** **B** para no distraer del fondo técnico. El TFM se evalúa por arquitectura y resultados RAG, no por branding.

**Impacto si responde tarde:** Bajo. Solo es estético; cambia 4-5 variables de Tailwind.

**Respuesta:** B

---

## P-10 — Deploy target del TFM

**Contexto.** El TFM puede entregarse con (i) solo el código + instrucciones de deploy local, o (ii) un deploy real accesible vía URL pública. §14 M7 menciona "deploy a un servidor accesible, screenshots para la memoria" sin especificar dónde.

**Pregunta:** ¿Dónde se va a desplegar (si en algún sitio) el MVP para la entrega?

**Opciones:**

- **A)** Solo local. El tribunal corre `docker-compose up`. README detallado.
- **B)** VPS personal (Hetzner, DigitalOcean, Contabo…) con Caddy + Let's Encrypt. URL pública con login.
- **C)** Cloud manado (Render, Railway, Fly.io). Más rápido de provisionar; coste mensual durante la defensa.
- **D)** Mezcla: local + un demo público con datos sintéticos cargados.

**Mi recomendación:** **A** para minimizar superficie. **D** si quieres impacto visual: tener una URL viva durante la defensa con un chatbot demo funcionando se ve muy bien.

**Impacto si responde tarde:** Medio. Cambia §12 (TLS, deploy concreto) y M7.

**Respuesta:** Si lo desplego sera en local para hacer una prueba, no nos complicamos. Por lo menos por ahora.

---

## Decisiones aplicadas por defecto (no bloquean, puedes revisarlas)

Estas decisiones las tomé yo durante el drafting porque parecían razonables y no había información en el handover/PDF para decidir contigo. Si alguna no encaja, dímelo y la cambio.

| Tema | Decisión aplicada | Si quieres cambiarla |
|---|---|---|
| Auto-ingest vs separar attach+ingest | Separados (2 endpoints) | Atomizar en un solo endpoint |
| Paginación | Page-based (`?page=N&page_size=M`) | Cursor-based |
| IDs | UUIDv7 | UUIDv4 |
| Modelo polimórfico de Sources | Una tabla con JSONB | Tablas separadas |
| Credenciales SQL | Tabla aparte `source_db_credentials` | Mezclar con `provider_credentials` |
| Denormalización de `tenant_id` | Sí en `chat_sessions` e `ingestion_jobs` | Solo por JOIN |
| Wizard | 7 pasos secuenciales | 3 pasos agrupados |
| Polling jobs | 2s mientras `running` | SSE/WebSocket |
| Distribución del widget | Servido por backend (`/widget.js`) | CDN externo |
| Algoritmo JWT | HS256 | RS256 |
| Límite upload | 50 MB/archivo, 10 archivos/request | Otros números |
| Rate limits | login 10/min/IP, public chat 60/min/(bot,IP), resto 600/min/tenant | Otros números |
| Métricas RAGAS | faithfulness + answer_relevance + context_precision + context_recall | Añadir/quitar |
| Idioma del panel | Solo español | Bilingüe ES/EN con i18n |
| Telemetría/observabilidad | structlog JSON | + Prometheus/OpenTelemetry/Sentry |
| Catálogo de proveedores | Vive en código (`domain/catalog/`) | UI superadmin |
| Soporte XLSX | Sí (Q5.1 ya cerrada) | Quitar y dejar PDF/DOCX/TXT/CSV/MD |

---

## Cómo continuar

Cuando respondas (aunque sea solo a las que te importen):

1. Aplico los cambios al HTML (`docs/superpowers/specs/2026-05-19-tfm-roadmap-funcional-design.html`) y al log.
2. Actualizo `handover.md`.
3. Invoco `writing-plans` para generar el plan de implementación.
4. El plan orquesta la extracción de las ~17 OpenSpec proposals en orden del grafo de deps.
