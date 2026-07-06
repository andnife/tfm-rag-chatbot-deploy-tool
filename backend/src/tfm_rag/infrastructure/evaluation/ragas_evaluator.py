"""RAGAS metrics computation, wrapped behind a small adapter.

RAGAS 0.2.x exposes:
- ``ragas.evaluate(dataset, metrics, llm, embeddings)`` → Result
- ``ragas.EvaluationDataset.from_list(rows)`` → typed dataset
- ``ragas.metrics`` module with metric instances (``faithfulness``, etc.)

We need an LLM and embeddings to ground the judge prompts. RAGAS uses
LangChain LLM wrappers, so we wire it to **Ollama via langchain-ollama**.
This is intentionally a separate Ollama client from the chatbot's
``OllamaLLMAdapter`` — we don't want RAGAS depending on our internal
adapters and vice-versa.

The eval extras (`ragas`, `langchain-ollama`, etc.) are an optional
dependency group; import errors at module load are surfaced verbatim so
the user runs ``pip install -e '.[eval]'``.
"""
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_ollama import OllamaEmbeddings, OllamaLLM
from ragas import EvaluationDataset, evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)
from ragas.run_config import RunConfig

from tfm_rag.domain.catalog.eval_metrics import RagasMetric
from tfm_rag.domain.catalog.eval_scenarios import (
    SCENARIO_ABSTAIN,
    SCENARIO_DOC_ONLY,
    SCENARIO_MIXED,
    SCENARIO_SQL_ONLY,
)
from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase
from tfm_rag.infrastructure.evaluation.judge_token_callback import JudgeTokenCallback

# `RagasMetric` now lives in the domain (pure metric-name vocabulary);
# re-exported here so existing import paths keep working.
__all__ = ["RagasEvaluator", "RagasMetric", "did_abstain", "routing_accuracy"]

_METRICS = (faithfulness, answer_relevancy, context_precision, context_recall)

_log = logging.getLogger(__name__)

# Fallback-only heuristic (used when the judge LLM call fails). Primary
# abstention detection is semantic, done by the judge LLM — see
# RagasEvaluator._judge_abstained. Substring, not prefix: an LLM abstention is
# free-form ("Lo siento, pero no tengo información…") and rarely opens with a
# fixed token, and the dataset (and answers) are in Spanish.
_ABSTAIN_ANSWER_HINTS = (
    "i don't know", "i dont know", "no tengo información", "no tengo informacion",
    "no dispongo de", "no hay información", "no hay informacion", "no puedo responder",
    "no se proporciona", "no figura", "no aparece",
)

_ABSTAIN_JUDGE_PROMPT = (
    "Eres un evaluador imparcial. Decide si el ASISTENTE se ABSTUVO de responder.\n"
    "Cuenta como abstención si el asistente declinó dar el dato pedido: dijo que no "
    "tiene o no encuentra la información, que no puede responder, o que el dato no "
    "está disponible en sus fuentes — en lugar de aportar un dato concreto. "
    "Aportar un dato o valor real cuenta como NO abstención.\n\n"
    "Pregunta del usuario:\n{question}\n\n"
    "Respuesta del asistente:\n{answer}\n\n"
    "¿El asistente se abstuvo? Responde ÚNICAMENTE con una palabra: SI o NO."
)


def _looks_like_abstention(answer: str) -> bool:
    """Cheap string heuristic — fallback for when the judge LLM is unavailable."""
    a = (answer or "").strip().lower()
    return any(hint in a for hint in _ABSTAIN_ANSWER_HINTS)


def did_abstain(case: EvaluationCase) -> bool:
    """True if the chatbot declined to answer this case (string heuristic).

    NOTE: this is the *fallback* path. Primary abstention detection is
    semantic, via the judge LLM (``RagasEvaluator._judge_abstained``); this
    remains for judge outages and for direct callers/tests.
    """
    return _looks_like_abstention(case.predicted_answer or "")


_EXPECTED_ROUTE: dict[str, str] = {
    SCENARIO_DOC_ONLY: "docs",
    SCENARIO_SQL_ONLY: "sql",
    SCENARIO_MIXED: "both",
}


def routing_accuracy(case: EvaluationCase) -> float | None:
    """1.0 si la ruta elegida por el router coincide con la esperada para el
    escenario de la fila, 0.0 si no. None cuando no aplica (escenario sin ruta
    esperada, p.ej. abstain, o sin traza de routing)."""
    expected = _EXPECTED_ROUTE.get(case.scenario)
    if expected is None:
        return None
    actual = (case.routing_trace or {}).get("route")
    if not actual:
        return None
    return 1.0 if actual == expected else 0.0


@dataclass(frozen=True)
class RagasEvaluator:
    """Compute RAGAS metrics for a batch of EvaluationCase.

    The judge LLM is selected by ``judge_provider`` (all fields are resolved
    from the chosen credential by the caller via ``resolve_inference_target``):
      * ``"ollama"`` — local ``OllamaLLM`` at ``base_url`` / ``judge_model``.
      * ``"openai"`` / ``"openai_compat"`` — ``ChatOpenAI`` at ``judge_base_url``
        with ``judge_api_key`` (required; there is no env-var fallback). Use a
        judge of a different family than the generator to avoid self-preference
        bias when grading a model with itself.

    Embeddings always use Ollama (``base_url`` / ``embedding_model``) — they
    feed context_precision/recall and don't need to match the judge, so we
    keep them local and free.

    ``temperature`` is fixed at 0.0 for reproducibility (per spec §13: "Seed
    fijo (temperatura 0 en LLM-as-judge).").

    Cases without ``predicted_answer`` or ``retrieved_contexts`` or with
    ``error`` set are skipped; the returned list keeps positional
    alignment by emitting ``{}`` for those slots.
    """

    base_url: str
    judge_model: str
    embedding_model: str
    temperature: float = 0.0
    judge_provider: str = "ollama"
    judge_base_url: str | None = None
    judge_api_key: str | None = None
    # Concurrency cap for RAGAS judge calls. When set (e.g. from the judge
    # credential's max_concurrency), it overrides the RAGAS_MAX_WORKERS env
    # default so a rate-limited judge endpoint isn't stormed. None = env/default.
    max_workers: int | None = None
    # Minimum spacing between judge requests, in seconds (from the credential's
    # min_request_interval_seconds). Applied to the openai/openai_compat judge
    # via a LangChain InMemoryRateLimiter. None = no spacing.
    min_request_interval_seconds: float | None = None
    # Per-call timeout (seconds) for the openai/openai_compat judge, so a judge
    # endpoint that opens a connection and never responds can't block scoring
    # forever. None → resolved from RAGAS_JUDGE_TIMEOUT env (default 60) in
    # _build_raw_judge_llm. OllamaLLM has no timeout param, so it's ignored there.
    judge_timeout_seconds: float | None = None
    # Optional: called with the running judge-call count after each judge call
    # (drives the live scoring progress bar). Not part of value identity.
    on_judge_progress: Callable[[int], None] | None = field(
        default=None, compare=False, repr=False
    )

    # Set in __post_init__ via object.__setattr__ (the dataclass is frozen);
    # declared here with init=False so they're not constructor params and so
    # mypy knows they exist on the class.
    _judge_cb: JudgeTokenCallback = field(init=False, repr=False, compare=False)
    last_judge_prompt_tokens: int = field(init=False, default=0, repr=False, compare=False)
    last_judge_completion_tokens: int = field(
        init=False, default=0, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        # frozen=True forbids normal attribute assignment; bypass it for the
        # mutable callback object that lives alongside the immutable config.
        object.__setattr__(
            self, "_judge_cb", JudgeTokenCallback(on_progress=self.on_judge_progress)
        )
        object.__setattr__(self, "last_judge_prompt_tokens", 0)
        object.__setattr__(self, "last_judge_completion_tokens", 0)

    def _build_raw_judge_llm(self) -> Any:
        """The raw LangChain judge model for the configured provider. Reused for
        RAGAS metric scoring (wrapped) and for the semantic abstention check
        (invoked directly)."""
        if self.judge_provider == "ollama":
            return OllamaLLM(
                base_url=self.base_url,
                model=self.judge_model,
                temperature=self.temperature,
                callbacks=[self._judge_cb],
            )
        if self.judge_provider in ("openai", "openai_compat"):
            from langchain_core.rate_limiters import InMemoryRateLimiter
            from langchain_openai import ChatOpenAI

            api_key = self.judge_api_key
            if not api_key:
                raise ValueError(
                    f"judge_provider={self.judge_provider!r} needs an API key "
                    f"(set judge_api_key on the credential)"
                )
            # PROACTIVE: space requests to the credential's min interval so we
            # stay under the provider's rate limit (requests_per_second =
            # 1/interval; bucket size 1 → strict spacing, no bursting).
            rate_limiter = None
            if self.min_request_interval_seconds and self.min_request_interval_seconds > 0:
                rate_limiter = InMemoryRateLimiter(
                    requests_per_second=1.0 / self.min_request_interval_seconds,
                    check_every_n_seconds=min(0.1, self.min_request_interval_seconds / 10),
                    max_bucket_size=1,
                )
            # REACTIVE: the openai SDK retries HTTP 429 honoring Retry-After;
            # a generous max_retries absorbs rate-limit bursts even if the
            # proactive spacing is absent or a provider's real limit is lower.
            # HARD STOP: a judge call must never block indefinitely (an endpoint
            # that opens an SSL connection and never responds will otherwise hang
            # the whole scoring phase). ChatOpenAI raises on timeout;
            # _judge_abstained catches it (falls back to the string heuristic)
            # and RAGAS marks the metric NaN.
            timeout = (
                self.judge_timeout_seconds
                if self.judge_timeout_seconds is not None
                else float(os.environ.get("RAGAS_JUDGE_TIMEOUT", "60"))
            )
            kwargs: dict[str, Any] = dict(
                model=self.judge_model,
                base_url=self.judge_base_url,
                api_key=api_key,
                temperature=self.temperature,
                max_retries=int(os.environ.get("RAGAS_JUDGE_MAX_RETRIES", "8")),
                timeout=timeout,
                callbacks=[self._judge_cb],
            )
            if rate_limiter is not None:
                kwargs["rate_limiter"] = rate_limiter
            return ChatOpenAI(**kwargs)
        raise ValueError(f"unknown judge_provider: {self.judge_provider!r}")

    def _build_judge_llm(self) -> LangchainLLMWrapper:
        """Wrap the raw judge model for RAGAS metric scoring."""
        return LangchainLLMWrapper(self._build_raw_judge_llm())

    def _judge_abstained(self, raw_judge: Any, question: str, answer: str) -> bool:
        """Ask the judge LLM whether *answer* abstains (declines to give the
        requested fact) vs. gives a substantive answer. Language- and
        phrasing-agnostic; falls back to the string heuristic if the judge call
        or its parsing fails. An empty answer counts as an abstention."""
        if not (answer or "").strip():
            return True
        prompt = _ABSTAIN_JUDGE_PROMPT.format(question=question, answer=answer)
        try:
            resp = raw_judge.invoke(prompt)
            text = getattr(resp, "content", resp)
            tokens = str(text).strip().lower().lstrip("\"'*-•> ").split()
            first = tokens[0].strip(".,:;!?") if tokens else ""
            return first in {"si", "sí", "yes", "true", "abstuvo", "abstain"}
        except Exception:  # noqa: BLE001 — a judge outage must not crash scoring
            _log.warning(
                "abstain judge call failed; falling back to string heuristic",
                exc_info=True,
            )
            return _looks_like_abstention(answer)

    def evaluate(
        self, cases: list[EvaluationCase]
    ) -> list[dict[str, float]]:
        out: list[dict[str, float]] = [{} for _ in cases]

        scorable_indices: list[int] = []
        rows: list[dict[str, Any]] = []
        raw_judge: Any = None  # built lazily, reused across abstain cases
        for i, case in enumerate(cases):
            if case.error is not None:
                continue
            # Abstain cases bypass RAGAS metrics (faithfulness/relevancy are
            # meaningless for an "I don't know"). The judge LLM decides
            # semantically whether the answer abstained — language- and
            # phrasing-agnostic, unlike a fixed string match.
            if case.scenario == SCENARIO_ABSTAIN:
                if raw_judge is None:
                    raw_judge = self._build_raw_judge_llm()
                abstained = self._judge_abstained(
                    raw_judge, case.question, case.predicted_answer or ""
                )
                out[i] = {RagasMetric.ABSTAIN_ACCURACY: 1.0 if abstained else 0.0}
                continue
            if not case.predicted_answer:
                continue
            if not case.retrieved_contexts:
                continue
            scorable_indices.append(i)
            rows.append({
                "user_input": case.question,
                "response": case.predicted_answer,
                "retrieved_contexts": case.retrieved_contexts,
                "reference": case.ground_truth,
            })

        if not rows:
            return out

        # Reset the token counter before this run so each evaluate() call
        # gets a fresh tally (the callback accumulates across on_llm_end calls).
        self._judge_cb.reset()

        dataset = EvaluationDataset.from_list(rows)
        llm = self._build_judge_llm()
        embeddings = LangchainEmbeddingsWrapper(
            OllamaEmbeddings(
                base_url=self.base_url,
                model=self.embedding_model,
            )
        )
        # RAGAS defaults to 16 concurrent judge calls. Against a rate-limited
        # judge endpoint (e.g. Cerebras free = 5 req/min) that concurrency
        # storms the limit, RAGAS' internal retries time out, and most metrics
        # come back NaN. Cap workers / widen the per-job timeout via env so the
        # judge calls drip out under the rate limit. Defaults preserve the
        # previous behaviour (16 workers) for unthrottled judges (Ollama/OpenAI).
        # Precedence: the credential's max_concurrency (self.max_workers) wins;
        # else the RAGAS_MAX_WORKERS env; else 16.
        max_workers = (
            self.max_workers
            if self.max_workers is not None
            else int(os.environ.get("RAGAS_MAX_WORKERS", "16"))
        )
        run_config = RunConfig(
            max_workers=max_workers,
            timeout=int(os.environ.get("RAGAS_TIMEOUT", "180")),
            max_retries=int(os.environ.get("RAGAS_MAX_RETRIES", "10")),
            max_wait=int(os.environ.get("RAGAS_MAX_WAIT", "60")),
        )
        result = evaluate(
            dataset=dataset,
            metrics=list(_METRICS),
            llm=llm,
            embeddings=embeddings,
            run_config=run_config,
        )
        df = result.to_pandas()
        as_dict = df.to_dict()
        for metric_name in (
            RagasMetric.FAITHFULNESS,
            RagasMetric.ANSWER_RELEVANCY,
            RagasMetric.CONTEXT_PRECISION,
            RagasMetric.CONTEXT_RECALL,
        ):
            metric_col = as_dict.get(metric_name, {})
            for row_idx_str, value in metric_col.items():
                row_idx = (
                    int(row_idx_str) if not isinstance(row_idx_str, int)
                    else row_idx_str
                )
                if row_idx < 0 or row_idx >= len(rows):
                    continue
                global_idx = scorable_indices[row_idx]
                if value is None or (isinstance(value, float) and value != value):
                    # NaN check — RAGAS returns NaN when a metric fails
                    continue
                out[global_idx][metric_name] = float(value)

        # Persist token totals captured by the judge callback so callers can
        # read them after evaluate() returns (e.g. for cost accounting).
        # frozen=True requires object.__setattr__ for post-init mutation.
        object.__setattr__(self, "last_judge_prompt_tokens", self._judge_cb.prompt_tokens)
        object.__setattr__(self, "last_judge_completion_tokens", self._judge_cb.completion_tokens)

        # Routing accuracy: determinista, para todo caso con ruta esperada.
        for i, case in enumerate(cases):
            if case.error is not None:
                continue
            ra = routing_accuracy(case)
            if ra is not None:
                out[i][RagasMetric.ROUTING_ACCURACY] = ra

        return out
