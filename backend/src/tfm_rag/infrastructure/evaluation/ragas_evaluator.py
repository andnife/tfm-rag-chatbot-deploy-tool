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
from dataclasses import dataclass
from typing import Any

from langchain_ollama import OllamaEmbeddings, OllamaLLM
from ragas import EvaluationDataset, evaluate
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase


class RagasMetric:
    """String constants matching RAGAS's column names in the result frame.

    The CLI / report writer reference these to filter by metric. We do NOT
    use the metric *instances* in calling code — only their names.
    """

    FAITHFULNESS = "faithfulness"
    ANSWER_RELEVANCY = "answer_relevancy"
    CONTEXT_PRECISION = "context_precision"
    CONTEXT_RECALL = "context_recall"


_METRICS = (faithfulness, answer_relevancy, context_precision, context_recall)


@dataclass(frozen=True)
class RagasEvaluator:
    """Compute RAGAS metrics for a batch of EvaluationCase.

    ``base_url`` / ``judge_model`` / ``embedding_model`` configure the
    Ollama-backed judge. ``temperature`` is fixed at 0.0 for
    reproducibility (per spec §13: "Seed fijo (temperatura 0 en
    LLM-as-judge).").

    Cases without ``predicted_answer`` or ``retrieved_contexts`` or with
    ``error`` set are skipped; the returned list keeps positional
    alignment by emitting ``{}`` for those slots.
    """

    base_url: str
    judge_model: str
    embedding_model: str
    temperature: float = 0.0

    def evaluate(
        self, cases: list[EvaluationCase]
    ) -> list[dict[str, float]]:
        scorable_indices: list[int] = []
        rows: list[dict[str, Any]] = []
        for i, case in enumerate(cases):
            if case.error is not None:
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

        out: list[dict[str, float]] = [{} for _ in cases]
        if not rows:
            return out

        dataset = EvaluationDataset.from_list(rows)
        llm = LangchainLLMWrapper(
            OllamaLLM(
                base_url=self.base_url,
                model=self.judge_model,
                temperature=self.temperature,
            )
        )
        embeddings = LangchainEmbeddingsWrapper(
            OllamaEmbeddings(
                base_url=self.base_url,
                model=self.embedding_model,
            )
        )
        result = evaluate(
            dataset=dataset,
            metrics=list(_METRICS),
            llm=llm,
            embeddings=embeddings,
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
        return out
