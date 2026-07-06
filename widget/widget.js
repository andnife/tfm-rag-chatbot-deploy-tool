/**
 * RAG Chatbot Widget — vanilla JS, Shadow DOM, ~400 LOC.
 *
 * Embed:
 *   <script
 *     src="https://your-host/widget/widget.js"
 *     data-public-key="wgt_xxxxx"
 *     data-api-base="https://your-host"
 *     data-locale="es"
 *     async
 *   ></script>
 *
 * The widget reads its own script tag for config, fetches the chatbot's
 * widget_config from /api/public/chatbots/{public_key}/config, then renders
 * a chat bubble in the page corner. Click → expand → chat.
 *
 * `data-locale` selects the widget's own UI/aria strings (open/close chat,
 * send button, input label, fallback title/placeholder, error message) from
 * the STRINGS dictionary below. Defaults to "es"; currently "es" and "en"
 * are provided. This is independent from the chatbot's widget_config, whose
 * free-text fields (title, welcome_message, placeholder) are already
 * locale-agnostic strings chosen by the chatbot owner.
 *
 * Session continuity: the widget generates a random `public_session_cookie`
 * on first load and persists it (plus the resulting session_id) in
 * localStorage under a per-public-key key. Reload → resume the same chat.
 */
(function () {
  "use strict";

  const SCRIPT_EL = document.currentScript;
  if (!SCRIPT_EL) {
    console.error("[tfm-widget] could not find currentScript; aborting");
    return;
  }

  const PUBLIC_KEY = SCRIPT_EL.getAttribute("data-public-key");
  if (!PUBLIC_KEY) {
    console.error("[tfm-widget] missing data-public-key on <script>");
    return;
  }
  const API_BASE = (
    SCRIPT_EL.getAttribute("data-api-base") || new URL(SCRIPT_EL.src).origin
  ).replace(/\/$/, "");

  // Optional visitor name supplied by the host page. When present, the
  // personalised greeting (welcome_message_named) is used with `{name}`
  // substituted; otherwise the anonymous welcome_message is shown.
  const USER_NAME = (SCRIPT_EL.getAttribute("data-user-name") || "").trim();

  const STORAGE_KEY = `tfm-widget:${PUBLIC_KEY}`;

  // ---- i18n: centralised UI/aria strings ------------------------------------
  //
  // Every visible or aria-* string the widget itself renders (i.e. not
  // supplied by the chatbot's widget_config, which already carries its own
  // free-text) lives here, keyed by locale. Host pages opt in via
  // `data-locale="en"` on the <script> tag; unknown/absent locales fall back
  // to "es".
  const STRINGS = {
    es: {
      openChat: "Abrir chat",
      closeChat: "Cerrar chat",
      defaultTitle: "Asistente",
      defaultPlaceholder: "Escribe tu pregunta...",
      inputLabel: "Escribe un mensaje para el asistente",
      send: "Enviar",
      errorMessage:
        "Lo siento, no he podido responder ahora. Inténtalo de nuevo en un momento.",
    },
    en: {
      openChat: "Open chat",
      closeChat: "Close chat",
      defaultTitle: "Assistant",
      defaultPlaceholder: "Type your question...",
      inputLabel: "Type a message to the assistant",
      send: "Send",
      errorMessage:
        "Sorry, I couldn't answer right now. Please try again in a moment.",
    },
  };
  const LOCALE = (SCRIPT_EL.getAttribute("data-locale") || "es").toLowerCase();
  const STR = STRINGS[LOCALE] || STRINGS.es;

  // ---- state persistence ---------------------------------------------------

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return { cookie: null, session_id: null, messages: [] };
      const parsed = JSON.parse(raw);
      return {
        cookie: parsed.cookie || null,
        session_id: parsed.session_id || null,
        messages: Array.isArray(parsed.messages) ? parsed.messages : [],
      };
    } catch (e) {
      return { cookie: null, session_id: null, messages: [] };
    }
  }

  function saveState(state) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (e) {
      /* quota / private mode — ignore */
    }
  }

  function generateCookie() {
    // 24 bytes = 192 bits of entropy. crypto.getRandomValues is required
    // — Math.random is predictable and unfit for session secrets.
    if (!(window.crypto && window.crypto.getRandomValues)) {
      throw new Error(
        "[tfm-widget] window.crypto.getRandomValues is unavailable; " +
        "session cookies cannot be generated securely. Modern browser required."
      );
    }
    const buf = new Uint8Array(24);
    window.crypto.getRandomValues(buf);
    return Array.from(buf)
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  }

  const state = loadState();
  if (!state.cookie) {
    state.cookie = generateCookie();
    saveState(state);
  }

  // ---- root container in Shadow DOM ----------------------------------------

  const host = document.createElement("div");
  host.id = "tfm-widget-host";
  host.style.cssText = "position:fixed;z-index:2147483647;";
  document.body.appendChild(host);
  const root = host.attachShadow({ mode: "open" });

  // ---- styles + markup -----------------------------------------------------

  const style = document.createElement("style");
  style.textContent = `
    :host, *, *::before, *::after { box-sizing: border-box; }
    .bubble {
      position: fixed; bottom: 20px; width: 56px; height: 56px;
      border-radius: 28px; border: none; cursor: pointer;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
      color: #fff; font-size: 28px; line-height: 56px;
      transition: transform .15s ease;
    }
    .bubble:hover { transform: scale(1.05); }
    .panel {
      position: fixed; bottom: 88px; width: 360px; max-width: 92vw;
      height: 520px; max-height: 80vh; border-radius: 12px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.2);
      display: none; flex-direction: column; overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                   Helvetica, Arial, sans-serif;
    }
    .panel.open { display: flex; }
    .panel.theme-light { background: #fff; color: #111; }
    .panel.theme-dark { background: #1f2937; color: #f9fafb; }
    .header {
      padding: 12px 16px; color: #fff;
      display: flex; align-items: center; justify-content: space-between;
    }
    .header-title { font-weight: 600; font-size: 15px; }
    .header-close {
      background: none; border: none; color: inherit; cursor: pointer;
      font-size: 20px; line-height: 1; padding: 0 4px;
    }
    .messages {
      flex: 1; padding: 12px 14px; overflow-y: auto;
      display: flex; flex-direction: column; gap: 8px;
    }
    .msg {
      max-width: 85%; padding: 8px 12px; border-radius: 12px;
      font-size: 14px; line-height: 1.4; white-space: pre-wrap;
      word-wrap: break-word;
    }
    .msg.user { align-self: flex-end; color: #fff; }
    .panel.theme-light .msg.assistant { background: #f3f4f6; color: #111; }
    .panel.theme-dark .msg.assistant { background: #374151; color: #f9fafb; }
    .typing {
      padding: 8px 12px; opacity: 0.7; font-size: 14px;
      align-self: flex-start;
    }
    .input-row {
      display: flex; gap: 8px; padding: 10px 12px;
      border-top: 1px solid rgba(0,0,0,0.08);
    }
    .panel.theme-dark .input-row {
      border-top: 1px solid rgba(255,255,255,0.08);
    }
    .input {
      flex: 1; resize: none; border: 1px solid rgba(0,0,0,0.15);
      border-radius: 8px; padding: 8px 10px; font: inherit;
      background: inherit; color: inherit;
    }
    .panel.theme-dark .input { border-color: rgba(255,255,255,0.15); }
    .input:focus { outline: none; border-color: var(--primary, #3b82f6); }
    .send {
      border: none; border-radius: 8px; padding: 0 14px; color: #fff;
      font-weight: 600; cursor: pointer;
    }
    .send:disabled { opacity: 0.5; cursor: default; }
  `;
  root.appendChild(style);

  const panel = document.createElement("div");
  panel.className = "panel theme-light";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "true");
  panel.setAttribute("aria-labelledby", "tfm-widget-title");
  root.appendChild(panel);

  const bubble = document.createElement("button");
  bubble.className = "bubble";
  bubble.textContent = "💬";
  bubble.setAttribute("aria-label", STR.openChat);
  root.appendChild(bubble);

  // Slots we'll fill once config arrives:
  let messagesEl = null;
  let inputEl = null;
  let sendEl = null;

  // ---- API client ----------------------------------------------------------

  const CONFIG_TIMEOUT_MS = 10_000;
  const CHAT_TIMEOUT_MS = 60_000;

  function fetchWithTimeout(url, opts, timeoutMs) {
    const ac = new AbortController();
    const t = setTimeout(() => ac.abort(), timeoutMs);
    return fetch(url, { ...opts, signal: ac.signal }).finally(() =>
      clearTimeout(t)
    );
  }

  async function fetchConfig() {
    const r = await fetchWithTimeout(
      `${API_BASE}/api/public/chatbots/${encodeURIComponent(PUBLIC_KEY)}/config`,
      { mode: "cors" },
      CONFIG_TIMEOUT_MS
    );
    if (!r.ok) throw new Error(`config fetch ${r.status}`);
    return r.json();
  }

  async function postChat(messageText) {
    const r = await fetchWithTimeout(
      `${API_BASE}/api/public/chatbots/${encodeURIComponent(PUBLIC_KEY)}/chat`,
      {
        method: "POST",
        mode: "cors",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          session_id: state.session_id,
          public_session_cookie: state.cookie,
          message: messageText,
        }),
      },
      CHAT_TIMEOUT_MS
    );
    if (!r.ok) {
      const text = await r.text();
      throw new Error(`chat ${r.status}: ${text}`);
    }
    return r.json();
  }

  // ---- UI rendering --------------------------------------------------------

  function applyConfig(cfg) {
    const w = cfg.widget || {};
    const primary = w.primary_color || "#3b82f6";
    panel.style.setProperty("--primary", primary);
    panel.className = `panel theme-${w.theme === "dark" ? "dark" : "light"}`;
    bubble.style.background = primary;
    // Position (bottom-left vs bottom-right):
    const side = w.position === "bottom-left" ? "left" : "right";
    bubble.style[side] = "20px";
    panel.style[side] = "20px";
    bubble.style[side === "left" ? "right" : "left"] = "auto";
    panel.style[side === "left" ? "right" : "left"] = "auto";

    // Header
    const header = document.createElement("div");
    header.className = "header";
    header.style.background = primary;
    const title = document.createElement("div");
    title.className = "header-title";
    title.id = "tfm-widget-title";
    title.textContent = w.title || STR.defaultTitle;
    const closeBtn = document.createElement("button");
    closeBtn.className = "header-close";
    closeBtn.setAttribute("aria-label", STR.closeChat);
    closeBtn.textContent = "✕";
    closeBtn.addEventListener("click", () => panel.classList.remove("open"));
    header.appendChild(title);
    header.appendChild(closeBtn);
    panel.appendChild(header);

    // Message list
    messagesEl = document.createElement("div");
    messagesEl.className = "messages";
    messagesEl.setAttribute("aria-live", "polite");
    panel.appendChild(messagesEl);

    // Input row
    const row = document.createElement("div");
    row.className = "input-row";
    inputEl = document.createElement("textarea");
    inputEl.className = "input";
    inputEl.rows = 1;
    inputEl.placeholder = w.placeholder || STR.defaultPlaceholder;
    inputEl.setAttribute("aria-label", STR.inputLabel);
    sendEl = document.createElement("button");
    sendEl.className = "send";
    sendEl.style.background = primary;
    sendEl.textContent = STR.send;
    row.appendChild(inputEl);
    row.appendChild(sendEl);
    panel.appendChild(row);

    // Restore prior conversation (or greet on a fresh session)
    if (state.messages.length === 0) {
      const greeting = pickGreeting(w);
      if (greeting) addMessage("assistant", greeting);
    } else {
      for (const m of state.messages) addMessage(m.role, m.content);
    }

    // Wire interactions
    bubble.addEventListener("click", () => {
      panel.classList.toggle("open");
      if (panel.classList.contains("open")) {
        setTimeout(() => inputEl.focus(), 50);
      }
    });
    sendEl.addEventListener("click", onSend);
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        onSend();
      }
    });
  }

  function pickGreeting(w) {
    // Personalised variant when the host gave us a name; otherwise the
    // anonymous one. Strip any stray `{name}` so we never show the literal
    // placeholder to the user.
    if (USER_NAME && w.welcome_message_named) {
      return w.welcome_message_named.split("{name}").join(USER_NAME);
    }
    const anon = w.welcome_message || "";
    return anon.replace(/\s*\{name\}\s*/g, " ").trim();
  }

  function addMessage(role, content) {
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    if (role === "user") el.style.background = bubble.style.background;
    el.textContent = content;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  let pending = false;
  async function onSend() {
    if (pending) return;
    const text = inputEl.value.trim();
    if (!text) return;

    inputEl.value = "";
    addMessage("user", text);
    state.messages.push({ role: "user", content: text });
    saveState(state);

    const typing = document.createElement("div");
    typing.className = "typing";
    typing.textContent = "...";
    messagesEl.appendChild(typing);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    sendEl.disabled = true;
    pending = true;

    try {
      const resp = await postChat(text);
      typing.remove();
      addMessage("assistant", resp.content);
      state.messages.push({ role: "assistant", content: resp.content });
      state.session_id = resp.session_id;
      saveState(state);
    } catch (e) {
      typing.remove();
      addMessage("assistant", STR.errorMessage);
      console.error("[tfm-widget] chat error", e);
    } finally {
      sendEl.disabled = false;
      pending = false;
      inputEl.focus();
    }
  }

  // ---- bootstrap -----------------------------------------------------------

  fetchConfig()
    .then(applyConfig)
    .catch((e) => {
      console.error("[tfm-widget] config fetch failed", e);
      // Render a minimal fallback so at least the bubble shows up
      applyConfig({
        widget: {
          theme: "light",
          primary_color: "#3b82f6",
          position: "bottom-right",
          title: STR.defaultTitle,
          welcome_message: "",
          placeholder: STR.defaultPlaceholder,
        },
      });
    });
})();
