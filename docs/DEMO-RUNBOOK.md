# Demo runbook — Defensa TFM (≈5 min, a prueba de balas)

Recorrido de un **usuario normal** por la plataforma, con todo pre-configurado e
ingestado. La evaluación (RAGAS/juez) NO va en el recorrido en vivo → va en las
diapositivas con los resultados de la memoria.

**Idea fuerza para el tribunal:** "una plataforma donde cualquiera configura y despliega
un chatbot RAG sobre sus propias fuentes (documentos + SQL), sin escribir código, y con
respuestas fundamentadas y honestas (cita fuentes y se abstiene si no sabe)."

---

## 0. Datos de la demo

| Cosa | Valor |
|---|---|
| Frontend | **http://localhost:3001** (¡el 3001, no el 3000!) |
| Usuario | `demo@fake.com` / `Demo1234` |
| KB | "Universidad Europea" (4 docs ya ingestados) — `269a91ee-fb60-49ac-a324-7638b22345d5` |
| Chatbot | "Asistente Universidad Europea" — `3ff4ec3c-8c24-487f-ae0b-45f731a1b416` |
| Modelo generación | DeepInfra (configúralo con tu API key el día de la demo) |
| Embeddings | Ollama `bge-m3` (local) |
| Playground (URL directa) | http://localhost:3001/chatbots/3ff4ec3c-8c24-487f-ae0b-45f731a1b416/playground |

> Re-provisionar la cuenta desde cero (idempotente): `bash scripts/seed-demo-universidad.sh`
> Smoke test del chat (12 preguntas): `bash scripts/demo-smoke.sh`

---

## 1. Checklist de pre-vuelo (hacer 15 min antes)

- [ ] **Docker Desktop** abierto y con WSL integration activa para Ubuntu.
- [ ] Servicios arriba: `docker compose -f infra/docker-compose.yml ps` → postgres, qdrant,
      mysql_source, ollama todos *healthy*.
- [ ] Backend sano: `curl -s http://localhost:8000/health` → `status: ok`.
- [ ] Frontend arriba en **:3001**: `curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/login` → `200`.
      (Si no: `bash scripts/run-frontend.sh --port 3001`)
- [ ] Ollama tiene `bge-m3`: `curl -s http://localhost:11434/api/tags | grep bge-m3`.
- [ ] **Credencial DeepInfra configurada** en la cuenta demo con tu API key (Settings →
      Credentials → Test → "OK"). El bot debe apuntar a ella.
- [ ] **⚠️ PRE-CALENTAR (crítico):** lanzar `bash scripts/demo-smoke.sh` UNA vez, o hacer
      una pregunta cualquiera en el Playground. La **primera** pregunta en frío tarda
      ~2 min (Ollama carga el modelo de embeddings); tras el calentamiento, 4-12 s.
      **Nunca hagas la primera pregunta de la demo en frío.**
- [ ] Pestañas del navegador ya abiertas en orden (login, dashboard, credentials, KB,
      chatbot edit, widget, playground) — o al menos la de login logueada.
- [ ] Zoom del navegador al 110-125 % para que se lea de lejos.
- [ ] **Presenta desde `http://localhost:3001`** (no desde IP/hostname de la LAN): en
      contexto no seguro el botón **Copiar** del widget falla en silencio
      (`navigator.clipboard` no existe). Desde localhost funciona.
- [ ] **Verifica la vista previa del widget**: que aparezca la burbuja de chat. Si sale
      solo el recuadro gris (el backend no sirve `/widget/widget.js` en tu layout),
      **evita esa pestaña** y enseña solo el snippet.
- [ ] **Red de seguridad:** screencast del recorrido ya grabado (lo grabas en el ensayo).

---

## 2. Guion minuto a minuto

### [0:00–0:30] Login + contexto (pantalla: `/login` → `/dashboard`)
- Entra con `demo@fake.com`.
- **Di:** *"Es una plataforma multi-tenant: cada organización tiene su espacio aislado.
  Al entrar veo el panel con mis bases de conocimiento y mis chatbots."*
- Enseña las tarjetas de resumen del dashboard.

### [0:30–1:00] Credenciales (pantalla: `/settings/credentials`)
- **Di:** *"La plataforma es agnóstica de proveedor de IA. Cada tenant conecta sus
  propios modelos: locales con Ollama, o cualquier proveedor compatible con OpenAI
  —aquí, DeepInfra—. Las claves se guardan cifradas."*
- (Opcional) pulsa **Test** en una credencial para mostrar el "OK".
- **⚠️ NO** abras el `.env` ni muestres claves en pantalla.

### [1:00–2:00] Base de conocimiento (pantalla: `/knowledge/<KB_ID>`)
- **Di:** *"Una base de conocimiento se alimenta de dos tipos de fuentes: documentos y
  bases de datos SQL."*
- Enseña los **4 documentos ya ingestados** (estado *done*).
- Abre el diálogo **Subir documento** (PDF/TXT/DOCX) para enseñar *cómo* se haría —
  **NO subas nada en vivo** (la ingestión + embeddings lleva tiempo). Ciérralo.
- **Di:** *"Al ingestar, cada documento se trocea y se vectoriza con un modelo de
  embeddings; aquí uso bge-m3 en local. Lo tengo ya hecho para no esperar."*
- (Opcional, luce bien y es rápido) usa el **panel de búsqueda/recuperación**: escribe
  "becas deportistas" y enseña los fragmentos recuperados con su score. Es puro
  retrieval, sin generación → instantáneo y sin riesgo.
- Menciona la fuente SQL: *"También podría conectar una base de datos MySQL/PostgreSQL
  y el chatbot consultaría datos en tiempo real; lo veréis en los resultados de
  evaluación de la memoria."*

### [2:00–2:45] Chatbot + Widget (pantallas: `/chatbots/<id>/edit` → `/widget`)
- En **edit**: enseña que el bot está cableado a la KB "Universidad Europea" y a un
  modelo de generación (DeepInfra). Menciona el *system prompt* (la persona del bot).
- En **widget**: enseña el snippet `<script ... data-public-key=...>`.
- **Di:** *"Con este fragmento, el chatbot se incrusta en cualquier web con dos líneas.
  Ese es el objetivo del TFM: del documento al asistente desplegado, sin programar."*
- (Opcional) pulsa **Copiar** para mostrar el copy-to-clipboard.

### [2:45–4:45] Playground — EL CLÍMAX (pantalla: `/chatbots/<id>/playground`)
Haz **3 preguntas** (todas verificadas; ver banco abajo). Deja que responda y comenta:

1. **Documental con cita:** *"¿Qué becas ofrece la universidad por buen expediente
   académico?"* → respuesta concreta (3.000 €, nota ≥ 7,5). **Abre las citas / el panel
   de iteración** y di: *"No alucina: recupera los fragmentos reales y cita la fuente."*
2. **Otra documental:** *"¿Ofrecen algún grado en Inteligencia Artificial? ¿En qué
   campus?"* → "Madrid y Valencia". Rápida y limpia.
3. **Abstención (el momento potente):** *"¿Quién es el rector actual de la
   universidad?"* → el bot **se abstiene con elegancia** ("No dispongo de esa
   información... contacta con admisiones"). **Di:** *"Y esto es clave: cuando la
   información no está en sus fuentes, lo reconoce en vez de inventar. Es un asistente
   honesto."*

### [4:45–5:00] Cierre
- **Di:** *"En resumen: crear la base de conocimiento, configurar el chatbot y
  desplegarlo, todo desde la interfaz. La calidad de las respuestas la medimos con una
  campaña de evaluación automática con métricas RAGAS y un juez LLM —los resultados
  están en la memoria—."*

---

## 3. Banco de preguntas verificado (Playground)

**Responden bien, con citas (elige 2-3):**
- ¿En qué ciudades tiene campus la Universidad Europea?
- ¿Qué es el Creative Campus y qué se estudia allí?
- ¿Ofrecen algún grado en Inteligencia Artificial? ¿En qué campus?
- ¿Puedo estudiar Diseño de Videojuegos de forma presencial? ¿Dónde?
- ¿Qué becas ofrece la universidad por buen expediente académico?
- ¿Hay becas para deportistas?
- ¿Cuáles son los pasos del proceso de admisión?
- ¿Los estudios incluyen prácticas en empresas?
- ¿Ofrece la universidad programas internacionales o de intercambio?

**Abstención honesta (elige 1 para el momento potente):**
- ¿Quién es el rector actual de la universidad?
- ¿Cuánto cuesta exactamente la matrícula de un grado?
- ¿Cuál es el menú de la cafetería del campus de Alcobendas?

**❌ EVITAR** (el grader se abstiene en falso — no la uses en vivo):
- Preguntas del área de "salud" ("¿Qué grados ofrece en el área de salud?").
- Preguntas compuestas que mezclan dos intenciones ("grado de salud en Valencia + beca…").

---

## 4. Plan B (si algo falla en vivo)

| Falla | Reacción |
|---|---|
| El chat tarda o da error de proveedor | "Voy a mostrarlo con el recorrido grabado" → screencast. |
| Frontend caído | `bash scripts/run-frontend.sh --port 3001` (o usa el screencast). |
| Backend caído | `bash scripts/start-bg.sh` + esperar `/health` ok. |
| Primera pregunta lentísima | Ya deberías haber pre-calentado; si no, explícalo: "primera carga del modelo". |
| Una pregunta responde raro | Pasa a otra del banco verificado; no improvises preguntas nuevas. |

**Regla de oro:** solo preguntas del banco verificado. No improvises en vivo.
