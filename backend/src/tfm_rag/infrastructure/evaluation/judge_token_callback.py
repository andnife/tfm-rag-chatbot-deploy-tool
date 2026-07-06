"""LangChain callback that captures token usage from the RAGAS judge LLM.

Attach an instance of this callback to the judge LLM at construction time
(``ChatOpenAI(..., callbacks=[cb])`` / ``OllamaLLM(..., callbacks=[cb])``).
Because it is an *instance-level* callback, LangChain fires ``on_llm_end``
for every generation regardless of whether RAGAS forwards its own callbacks.

After ``ragas.evaluate()`` returns, read the accumulated counters:
    cb.prompt_tokens     → int  (0 if the provider returned no usage info)
    cb.completion_tokens → int

Call ``cb.reset()`` before each ``evaluate()`` call if the same evaluator
instance is reused across multiple runs (RagasEvaluator already does this).

Token extraction logic
-----------------------
OpenAI-family (ChatOpenAI / openai_compat):
    response.llm_output["token_usage"]["prompt_tokens" | "completion_tokens"]

Ollama (OllamaLLM), fallback when llm_output has no token_usage:
    response.generations[i][j].generation_info["prompt_eval_count" | "eval_count"]

Both paths are tolerant of missing keys / None values — they add 0 and never
raise, so a missing-usage result doesn't crash the evaluation run.
"""

from collections.abc import Callable
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


class JudgeTokenCallback(BaseCallbackHandler):
    """Accumulates prompt + completion tokens from a judge LLM's responses, and
    counts finished calls.

    ``on_progress`` (optional) is invoked with the running call count after each
    finished judge call — the background eval job uses it to publish live
    scoring progress (the RAGAS scoring phase is a single blocking batch with no
    per-item events of its own, so this callback is the only progress signal)."""

    def __init__(self, on_progress: Callable[[int], None] | None = None) -> None:
        super().__init__()
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.calls: int = 0
        self.on_progress = on_progress

    # ------------------------------------------------------------------
    # public helpers
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset counters to zero (call before each evaluate() run)."""
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.calls = 0

    # ------------------------------------------------------------------
    # LangChain callback hook
    # ------------------------------------------------------------------

    def on_llm_end(self, response: object, **kwargs: object) -> None:
        """Accumulate token usage from a finished LLM call.

        Tries the OpenAI-family path first (``llm_output["token_usage"]``);
        falls back to per-generation ``generation_info`` for Ollama.
        """
        self.calls += 1
        if self.on_progress is not None:
            self.on_progress(self.calls)

        llm_output: dict[str, Any] | None = getattr(response, "llm_output", None) or {}

        token_usage: dict[str, Any] | None = (
            llm_output.get("token_usage") if isinstance(llm_output, dict) else None
        )

        if token_usage:
            # OpenAI-family: {"prompt_tokens": int, "completion_tokens": int}
            self.prompt_tokens += int(token_usage.get("prompt_tokens") or 0)
            self.completion_tokens += int(token_usage.get("completion_tokens") or 0)
            return

        # Ollama fallback: read from generation_info on each generation chunk
        generations = getattr(response, "generations", None) or []
        for gen_list in generations:
            for gen in (gen_list if isinstance(gen_list, list) else [gen_list]):
                info: dict[str, Any] = getattr(gen, "generation_info", None) or {}
                self.prompt_tokens += int(info.get("prompt_eval_count") or 0)
                self.completion_tokens += int(info.get("eval_count") or 0)
