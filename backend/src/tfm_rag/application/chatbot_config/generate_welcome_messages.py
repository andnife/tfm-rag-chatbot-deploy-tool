"""Generate the chatbot's two welcome-message variants from its knowledge.

The chatbot greets the user on chat open (narrative §1.4.1). Rather than make
the admin write the greeting, the platform drafts it automatically from the
chatbot's purpose (system prompt) and the knowledge bases it can access, in two
variants:

  - **anonymous**: no reference to the user (used when the host page provides
    no visitor name, e.g. an embedded widget on a public site).
  - **named**: contains the `{name}` placeholder, substituted client-side when
    a visitor name is available.

Both are suggestions the admin can edit. Generation never fails the caller: any
LLM error / malformed output falls back to sensible static defaults.
"""
import json
import logging
from dataclasses import dataclass

from tfm_rag.domain.ports.llm import LLMProvider
from tfm_rag.domain.value_objects.retrieval_iteration import LLMTextResponse

_log = logging.getLogger(__name__)

# Kept in sync with WidgetConfig field limits.
_MAX_LEN = 500

DEFAULT_ANONYMOUS = "¿En qué puedo ayudarte?"
DEFAULT_NAMED = "Hola {name}, ¿en qué puedo ayudarte?"

_NAME_PLACEHOLDER = "{name}"


@dataclass(frozen=True, slots=True)
class WelcomeMessages:
    anonymous: str
    named: str


def _build_messages(
    system_prompt: str, kb_summaries: list[str]
) -> list[dict[str, object]]:
    knowledge = (
        "\n".join(f"- {s}" for s in kb_summaries if s.strip())
        or "- (sin bases de conocimiento todavía)"
    )
    instruction = (
        "Eres un asistente que redacta el mensaje de bienvenida de un chatbot "
        "de atención al cliente. A partir del rol del chatbot y de las fuentes "
        "de conocimiento a las que tiene acceso, redacta un saludo breve (1-2 "
        "frases) que indique de forma natural sobre qué puede ayudar.\n\n"
        f"Rol del chatbot:\n{system_prompt.strip() or '(sin rol definido)'}\n\n"
        f"Conocimiento disponible:\n{knowledge}\n\n"
        "Devuelve EXCLUSIVAMENTE un objeto JSON con dos claves:\n"
        '  "anonymous": el saludo sin mencionar al usuario.\n'
        '  "named": el mismo saludo pero incluyendo el marcador literal '
        f"{_NAME_PLACEHOLDER} donde iría el nombre del usuario.\n"
        "No añadas texto fuera del JSON."
    )
    return [{"role": "user", "content": instruction}]


def _extract_json_object(text: str) -> dict[str, object]:
    """Pull the first {...} JSON object out of an LLM reply, tolerating
    markdown fences or surrounding prose. Raises ValueError if none parses."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in LLM reply")
    obj = json.loads(text[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError("parsed JSON is not an object")
    return obj


def _clamp(s: str) -> str:
    return s if len(s) <= _MAX_LEN else s[:_MAX_LEN].rstrip()


async def generate_welcome_messages(
    *,
    llm: LLMProvider,
    base_url: str,
    api_key: str | None,
    model_id: str,
    system_prompt: str,
    kb_summaries: list[str],
    temperature: float = 0.7,
) -> WelcomeMessages:
    fallback = WelcomeMessages(DEFAULT_ANONYMOUS, DEFAULT_NAMED)
    try:
        resp = await llm.generate(
            base_url=base_url,
            api_key=api_key,
            model_id=model_id,
            messages=_build_messages(system_prompt, kb_summaries),
            tools=None,
            temperature=temperature,
            top_p=1.0,
            max_tokens=300,
        )
        if not isinstance(resp, LLMTextResponse):
            return fallback
        data = _extract_json_object(resp.text)
        anon = str(data.get("anonymous", "")).strip()
        named = str(data.get("named", "")).strip()
        # Invariants: both non-empty and the named variant must carry the
        # placeholder so client-side substitution has something to replace.
        if not anon or not named or _NAME_PLACEHOLDER not in named:
            return fallback
        return WelcomeMessages(_clamp(anon), _clamp(named))
    except Exception as exc:  # noqa: BLE001 — generation must never fail the caller
        _log.info("welcome-message generation fell back to defaults: %s", exc)
        return fallback
