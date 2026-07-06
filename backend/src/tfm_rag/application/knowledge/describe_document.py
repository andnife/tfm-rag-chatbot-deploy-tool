"""Generate a short per-document description at ingestion time (sub-proyecto C1).

Best-effort: any failure returns None and the caller leaves the description
unset, so the router falls back to the filename (current behaviour).
"""
from tfm_rag.domain.ports.chunker import Chunk
from tfm_rag.domain.ports.llm import LLMProvider
from tfm_rag.domain.value_objects.retrieval_iteration import LLMTextResponse

_SAMPLE_SIZE = 5
_MAX_CHARS_PER_CHUNK = 500
_MAX_WORDS = 80
_TEMPERATURE = 0.2
_TOP_P = 1.0
_MAX_TOKENS = 200

_SYSTEM = (
    "You write a one-paragraph (2-3 sentence) description of what a document "
    "is about, to help route user questions to the right source. Be factual "
    "and concise. Do not add preamble like 'This document'."
)


def _sample(chunks: list[Chunk]) -> list[Chunk]:
    if len(chunks) <= _SAMPLE_SIZE:
        return chunks
    step = (len(chunks) - 1) / (_SAMPLE_SIZE - 1)
    idxs = sorted({round(i * step) for i in range(_SAMPLE_SIZE)})
    return [chunks[i] for i in idxs]


async def describe_document(
    chunks: list[Chunk],
    *,
    llm: LLMProvider,
    base_url: str,
    api_key: str | None,
    model_id: str,
) -> str | None:
    if not chunks:
        return None
    sample = _sample(chunks)
    excerpts = "\n\n".join(c.text[:_MAX_CHARS_PER_CHUNK] for c in sample)
    messages: list[dict[str, object]] = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user",
         "content": f"Document excerpts:\n{excerpts}\n\nDescribe this document."},
    ]
    try:
        resp = await llm.generate(
            base_url=base_url, api_key=api_key, model_id=model_id,
            messages=messages, tools=None,
            temperature=_TEMPERATURE, top_p=_TOP_P, max_tokens=_MAX_TOKENS,
        )
    except Exception:  # noqa: BLE001 - best-effort enrichment, never raise
        return None
    if not isinstance(resp, LLMTextResponse):
        return None
    words = resp.text.split()
    if not words:
        return None
    return " ".join(words[:_MAX_WORDS])
