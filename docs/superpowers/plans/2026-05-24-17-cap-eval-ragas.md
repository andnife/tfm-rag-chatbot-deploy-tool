# CAP-EVAL-RAGAS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `python -m tfm_rag.cli.eval_ragas --chatbot-id <uuid> --dataset <path> --scenario <name>` (CLI-only, academic mode) — reads a JSONL evaluation dataset, runs the chatbot's agent loop against each question, computes RAGAS metrics (faithfulness, answer_relevancy, context_precision, context_recall), and writes `report.json` + `report.md` on disk. This is the academic-evaluation piece of the TFM.

**Architecture:**
- **Reuse the agent loop.** Each question goes through the same `answer_query` use case the chat endpoint uses. We add two small affordances: (a) an optional `persist: bool = False` flag so eval runs don't pollute `chat_sessions` / `chat_messages`, and (b) a `retrieved_contexts: list[str]` field on `AnswerView` so we can hand the chunk texts to RAGAS without re-querying Qdrant. Both changes are backwards-compatible defaults.
- **RAGAS as a black-box library.** We wrap the `ragas` library behind a thin `RagasEvaluator` adapter (`infrastructure/evaluation/ragas_evaluator.py`). RAGAS itself needs an LLM and embeddings to compute its judge-based metrics; we wire it to **Ollama via `langchain-ollama`** (separate from our own `OllamaLLMAdapter`). This keeps the chatbot's LLM path untouched and matches RAGAS's documented integration pattern.
- **Heavy deps live in an `eval` extra.** `ragas`, `langchain-ollama`, `langchain-community`, `datasets` are big (transformers, etc.). They go into `[project.optional-dependencies].eval` so the API container stays lean. Install with `pip install -e '.[eval,dev]'`.
- **No new DB tables, no HTTP endpoints.** Pure offline pipeline. Reports land on disk; the CLI's `--output-dir` defaults to `eval_runs/<timestamp>/`.
- **Tagging:** `cap-17-eval-ragas` at the end (cleanup commit per project convention).

**Tech Stack:**
- `ragas>=0.2` (RAGAS 0.2.x — `EvaluationDataset.from_list` + `evaluate(...)` API)
- `langchain-ollama>=0.2` (`OllamaLLM` + `OllamaEmbeddings` wrappers used by RAGAS)
- `langchain-community>=0.3` (transitive enabler)
- `datasets>=3.0` (RAGAS uses HuggingFace datasets internally)
- `argparse` (stdlib, no new dep)

**Depends on:**
- Plan #10 (CAP-CHATBOT-LIFECYCLE — `ChatbotRepository.get` + `list_kb_ids`)
- Plan #12 (CAP-CHAT-DOC-RETRIEVAL — `retrieve_docs`)
- Plan #15 (CAP-CHAT-AGENT-LOOP — `answer_query`, `AnswerView`, `OllamaLLMAdapter`)

**Out of scope (deferred):**
- **Matrix comparison in one CLI invocation.** The spec mentions comparing reranker on/off, agentic_mode, chunk_size, LLMs, etc. Plan #17 runs ONE configuration per invocation; the user runs the CLI N times with N chatbots. A `compare-runs` subcommand can land later as a small follow-up.
- **Public-dataset auto-loaders** (RAG-12000, MS MARCO, SQuAD adapters). Caller provides a JSONL path; the format is documented.
- **SQL-source scenarios** (`sql_only`, `mixed`). The dataset format declares the scenario but the agent loop in plan #15 doesn't have `query_database` wired yet (plan #13 ships that). For now the `scenario` field is just metadata in the report; only `doc_only` and `abstain` actually exercise the loop in M3. The CLI accepts all scenario values without crashing.
- **DB persistence of evaluation runs.** Reports live on disk only. No `eval_runs` table.
- **Dashboard / HTTP endpoint.** CLI-only per spec §13 + §8.
- **Auto-generation of evaluation datasets.** Spec non-goal.
- **In-test SSE streaming progress** — `print(...)` progress to stdout is enough for CLI ergonomics.

**On centralised string constants (project policy):** scenario names live as constants in `domain/catalog/eval_scenarios.py` to avoid bare literals scattered around dataset loader + CLI + tests.

---

## File structure

```
backend/src/tfm_rag/
├── domain/
│   ├── catalog/
│   │   └── eval_scenarios.py                 # NEW: SCENARIO_* constants + KNOWN_SCENARIOS set
│   ├── value_objects/
│   │   ├── evaluation_case.py                # NEW: EvaluationCase (input + prediction + scores)
│   │   └── evaluation_report.py              # NEW: EvaluationSummary + EvaluationReport
│   └── errors/
│       └── evaluation.py                     # NEW: EvaluationDatasetError + EvaluationError
│
├── application/
│   ├── chat/
│   │   └── answer_query.py                   # MODIFY: AnswerView.retrieved_contexts + answer_query(persist=...)
│   └── evaluation/                           # NEW pkg
│       ├── __init__.py
│       ├── dataset_loader.py                 # NEW: load_evaluation_dataset(path) → list[EvaluationCase]
│       ├── report_writer.py                  # NEW: write_report(report, output_dir)
│       └── run_ragas_evaluation.py           # NEW: orchestrator use case
│
├── infrastructure/
│   └── evaluation/                           # NEW pkg
│       ├── __init__.py
│       └── ragas_evaluator.py                # NEW: wraps ragas + langchain-ollama
│
└── cli/
    ├── __init__.py                           # already exists (empty)
    └── eval_ragas.py                         # NEW: argparse main + bootstraps DB + runs the use case

backend/pyproject.toml                        # MODIFY: [project.optional-dependencies].eval + [project.scripts]

backend/tests/unit/
├── test_eval_scenarios.py                    # NEW: 3 tests
├── test_evaluation_case_vo.py                # NEW: 4 tests
├── test_evaluation_report_vo.py              # NEW: 4 tests
├── test_dataset_loader.py                    # NEW: 6 tests
├── test_answer_query_persist_and_contexts.py # NEW: 4 tests (existing test_answer_query.py untouched)
├── test_report_writer.py                     # NEW: 4 tests
└── test_run_ragas_evaluation.py              # NEW: 5 tests (fake evaluator)

backend/tests/integration/
└── test_eval_ragas_cli_flow.py               # NEW: 1 test (slow, runs CLI vs live Ollama)
```

---

## Task 1 — Domain: scenarios catalog + VOs + errors + dataset loader

**Files:**
- Create: `backend/src/tfm_rag/domain/catalog/eval_scenarios.py`
- Create: `backend/src/tfm_rag/domain/value_objects/evaluation_case.py`
- Create: `backend/src/tfm_rag/domain/value_objects/evaluation_report.py`
- Create: `backend/src/tfm_rag/domain/errors/evaluation.py`
- Create: `backend/src/tfm_rag/application/evaluation/__init__.py`
- Create: `backend/src/tfm_rag/application/evaluation/dataset_loader.py`
- Create: `backend/tests/unit/test_eval_scenarios.py`
- Create: `backend/tests/unit/test_evaluation_case_vo.py`
- Create: `backend/tests/unit/test_evaluation_report_vo.py`
- Create: `backend/tests/unit/test_dataset_loader.py`

- [ ] **Step 1.1: Write failing tests for the scenarios catalog**

Create `backend/tests/unit/test_eval_scenarios.py`:

```python
from tfm_rag.domain.catalog import eval_scenarios


def test_scenario_constants_have_expected_values() -> None:
    assert eval_scenarios.SCENARIO_DOC_ONLY == "doc_only"
    assert eval_scenarios.SCENARIO_SQL_ONLY == "sql_only"
    assert eval_scenarios.SCENARIO_MIXED == "mixed"
    assert eval_scenarios.SCENARIO_ABSTAIN == "abstain"


def test_known_scenarios_includes_all_four() -> None:
    assert eval_scenarios.KNOWN_SCENARIOS == {
        "doc_only", "sql_only", "mixed", "abstain",
    }


def test_is_known_scenario_recognises_known_and_unknown() -> None:
    assert eval_scenarios.is_known_scenario("doc_only") is True
    assert eval_scenarios.is_known_scenario("mixed") is True
    assert eval_scenarios.is_known_scenario("free-form") is False
```

- [ ] **Step 1.2: Run, confirm collection failure**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pytest tests/unit/test_eval_scenarios.py -v
```

Expected: collection error — module doesn't exist.

- [ ] **Step 1.3: Create `backend/src/tfm_rag/domain/catalog/eval_scenarios.py`**

```python
"""Catalog of evaluation scenarios for the RAGAS pipeline.

Single source of truth for the four scenarios declared in the spec
(§13 — Evaluación RAGAS). Used by the dataset loader (validating dataset
entries), the CLI (filtering by --scenario), and the report writer.

`sql_only` and `mixed` are declared here for future use but no chatbot
in M3 has a SQL source yet (plan #13 lands that). The eval pipeline
accepts dataset entries with those scenarios and simply records them in
the report; the chatbot will likely abstain since the agent loop has
no `query_database` tool wired.
"""

SCENARIO_DOC_ONLY = "doc_only"
SCENARIO_SQL_ONLY = "sql_only"
SCENARIO_MIXED = "mixed"
SCENARIO_ABSTAIN = "abstain"

KNOWN_SCENARIOS: frozenset[str] = frozenset({
    SCENARIO_DOC_ONLY,
    SCENARIO_SQL_ONLY,
    SCENARIO_MIXED,
    SCENARIO_ABSTAIN,
})


def is_known_scenario(name: str) -> bool:
    return name in KNOWN_SCENARIOS
```

- [ ] **Step 1.4: Run scenarios tests, expect 3 PASSED**

```bash
pytest tests/unit/test_eval_scenarios.py -v
```

Expected: **3 PASSED**.

- [ ] **Step 1.5: Write failing tests for `EvaluationCase`**

Create `backend/tests/unit/test_evaluation_case_vo.py`:

```python
import pytest

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase


def test_evaluation_case_minimal_input_fields() -> None:
    case = EvaluationCase(
        question="When did the war end?",
        ground_truth="In 1939.",
        scenario="doc_only",
        metadata={"difficulty": "easy"},
    )
    assert case.question == "When did the war end?"
    assert case.ground_truth == "In 1939."
    assert case.scenario == "doc_only"
    assert case.metadata == {"difficulty": "easy"}
    # Prediction fields default to None / [] until the chatbot has run.
    assert case.predicted_answer is None
    assert case.retrieved_contexts == []
    assert case.citations == []
    assert case.iterations == []
    assert case.scores is None
    assert case.error is None


def test_evaluation_case_with_prediction_and_scores() -> None:
    case = EvaluationCase(
        question="q",
        ground_truth="gt",
        scenario="doc_only",
        metadata={},
        predicted_answer="a",
        retrieved_contexts=["chunk-a", "chunk-b"],
        citations=[{"source_name": "f.pdf"}],
        iterations=[{"index": 0, "tool": "search_docs"}],
        scores={"faithfulness": 0.87, "answer_relevancy": 0.95},
    )
    assert case.predicted_answer == "a"
    assert case.retrieved_contexts == ["chunk-a", "chunk-b"]
    assert case.scores["faithfulness"] == 0.87


def test_evaluation_case_empty_question_rejected() -> None:
    with pytest.raises(ValidationError):
        EvaluationCase(
            question="   ",
            ground_truth="gt",
            scenario="doc_only",
            metadata={},
        )


def test_evaluation_case_to_dict_round_trip() -> None:
    case = EvaluationCase(
        question="q",
        ground_truth="gt",
        scenario="doc_only",
        metadata={"d": "easy"},
        predicted_answer="a",
        retrieved_contexts=["x"],
        scores={"faithfulness": 0.7},
    )
    data = case.to_dict()
    assert data["question"] == "q"
    assert data["scenario"] == "doc_only"
    assert data["predicted_answer"] == "a"
    assert data["retrieved_contexts"] == ["x"]
    assert data["scores"] == {"faithfulness": 0.7}
    assert data["error"] is None
```

- [ ] **Step 1.6: Create `backend/src/tfm_rag/domain/value_objects/evaluation_case.py`**

```python
from dataclasses import dataclass, field
from typing import Any

from tfm_rag.domain.errors.common import ValidationError


@dataclass(frozen=False, slots=True)
class EvaluationCase:
    """One entry in an evaluation run. Combines:

    - input from the dataset: ``question``, ``ground_truth``, ``scenario``, ``metadata``
    - prediction from the chatbot (filled after ``answer_query`` runs):
      ``predicted_answer``, ``retrieved_contexts``, ``citations``, ``iterations``
    - judge output (filled after ragas runs): ``scores`` (per-metric float in [0,1])
    - error path: ``error`` non-None means the case failed (LLM error,
      retrieval error, ragas crash); the rest may be partially filled.

    Mutable (``frozen=False``) on purpose — the pipeline fills fields in
    stages. Use ``to_dict()`` for JSON serialisation.
    """

    question: str
    ground_truth: str
    scenario: str
    metadata: dict[str, Any] = field(default_factory=dict)

    predicted_answer: str | None = None
    retrieved_contexts: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    iterations: list[dict[str, Any]] = field(default_factory=list)

    scores: dict[str, float] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.question or not self.question.strip():
            raise ValidationError("EvaluationCase.question must not be empty")
        if not self.scenario or not self.scenario.strip():
            raise ValidationError("EvaluationCase.scenario must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "ground_truth": self.ground_truth,
            "scenario": self.scenario,
            "metadata": self.metadata,
            "predicted_answer": self.predicted_answer,
            "retrieved_contexts": self.retrieved_contexts,
            "citations": self.citations,
            "iterations": self.iterations,
            "scores": self.scores,
            "error": self.error,
        }
```

- [ ] **Step 1.7: Run EvaluationCase tests, expect 4 PASSED**

```bash
pytest tests/unit/test_evaluation_case_vo.py -v
```

Expected: **4 PASSED**.

- [ ] **Step 1.8: Write failing tests for `EvaluationReport` + `EvaluationSummary`**

Create `backend/tests/unit/test_evaluation_report_vo.py`:

```python
from datetime import datetime, timezone
from uuid import uuid4

from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase
from tfm_rag.domain.value_objects.evaluation_report import (
    EvaluationReport,
    EvaluationSummary,
)


def _case(score_f: float = 0.7, score_ar: float = 0.8) -> EvaluationCase:
    return EvaluationCase(
        question="q",
        ground_truth="gt",
        scenario="doc_only",
        metadata={},
        predicted_answer="a",
        retrieved_contexts=["x"],
        scores={"faithfulness": score_f, "answer_relevancy": score_ar},
    )


def test_summary_averages_per_metric_skipping_errors() -> None:
    cases = [_case(0.6, 0.8), _case(0.8, 0.9), _case(0.5, 0.5)]
    # Add a failed case — it must be excluded from averages
    err = EvaluationCase(
        question="q4", ground_truth="gt", scenario="doc_only", metadata={},
        error="LLM timeout", scores=None,
    )
    cases.append(err)

    summary = EvaluationSummary.from_cases(cases)
    assert summary.num_cases == 4
    assert summary.num_errors == 1
    assert summary.num_scored == 3
    # avg = (0.6+0.8+0.5)/3 = 0.6333...
    assert abs(summary.metrics["faithfulness"] - 0.6333333) < 1e-4
    # avg = (0.8+0.9+0.5)/3 = 0.7333...
    assert abs(summary.metrics["answer_relevancy"] - 0.7333333) < 1e-4


def test_summary_with_no_scored_cases_yields_empty_metrics() -> None:
    err = EvaluationCase(
        question="q", ground_truth="gt", scenario="doc_only", metadata={},
        error="boom",
    )
    summary = EvaluationSummary.from_cases([err])
    assert summary.num_cases == 1
    assert summary.num_errors == 1
    assert summary.num_scored == 0
    assert summary.metrics == {}


def test_report_to_dict_contains_config_and_cases() -> None:
    chatbot_id = uuid4()
    when = datetime(2026, 5, 24, 10, 0, tzinfo=timezone.utc)
    cases = [_case()]
    report = EvaluationReport(
        chatbot_id=chatbot_id,
        chatbot_name="HistoryBot",
        dataset_path="/tmp/ds.jsonl",
        scenario_filter="doc_only",
        run_started_at=when,
        run_finished_at=when,
        ragas_judge_model="llama3.1",
        cases=cases,
        summary=EvaluationSummary.from_cases(cases),
    )
    data = report.to_dict()
    assert data["chatbot_id"] == str(chatbot_id)
    assert data["chatbot_name"] == "HistoryBot"
    assert data["dataset_path"] == "/tmp/ds.jsonl"
    assert data["scenario_filter"] == "doc_only"
    assert data["ragas_judge_model"] == "llama3.1"
    assert data["run_started_at"] == when.isoformat()
    assert isinstance(data["cases"], list)
    assert len(data["cases"]) == 1
    assert data["summary"]["num_cases"] == 1


def test_report_top_failures_returns_worst_cases_per_metric() -> None:
    good = _case(0.9, 0.9)
    bad = _case(0.1, 0.95)
    worse = _case(0.05, 0.5)
    report = EvaluationReport(
        chatbot_id=uuid4(),
        chatbot_name="X",
        dataset_path="/tmp/ds.jsonl",
        scenario_filter=None,
        run_started_at=datetime.now(timezone.utc),
        run_finished_at=datetime.now(timezone.utc),
        ragas_judge_model="llama3.1",
        cases=[good, bad, worse],
        summary=EvaluationSummary.from_cases([good, bad, worse]),
    )
    top = report.top_failures(metric="faithfulness", n=2)
    assert len(top) == 2
    # Lowest faithfulness scores first
    assert top[0].scores["faithfulness"] == 0.05
    assert top[1].scores["faithfulness"] == 0.1
```

- [ ] **Step 1.9: Create `backend/src/tfm_rag/domain/value_objects/evaluation_report.py`**

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    """Aggregated metrics across the cases in an evaluation run.

    Errored cases (``case.error is not None``) are skipped when computing
    averages — they're counted in ``num_errors``.
    """

    num_cases: int
    num_errors: int
    num_scored: int
    metrics: dict[str, float] = field(default_factory=dict, hash=False)

    @classmethod
    def from_cases(cls, cases: list[EvaluationCase]) -> "EvaluationSummary":
        scored = [c for c in cases if c.error is None and c.scores]
        errored = [c for c in cases if c.error is not None]

        averages: dict[str, float] = {}
        if scored:
            metric_names: set[str] = set()
            for c in scored:
                metric_names.update(c.scores.keys())  # type: ignore[union-attr]
            for name in metric_names:
                vals = [
                    c.scores[name]  # type: ignore[index]
                    for c in scored
                    if c.scores and name in c.scores
                ]
                if vals:
                    averages[name] = sum(vals) / len(vals)

        return cls(
            num_cases=len(cases),
            num_errors=len(errored),
            num_scored=len(scored),
            metrics=averages,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "num_cases": self.num_cases,
            "num_errors": self.num_errors,
            "num_scored": self.num_scored,
            "metrics": self.metrics,
        }


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Full output of one CLI invocation.

    Persisted as JSON via ``to_dict()`` + ``json.dumps``, and rendered as a
    human-readable Markdown digest by ``report_writer``.
    """

    chatbot_id: UUID
    chatbot_name: str
    dataset_path: str
    scenario_filter: str | None
    run_started_at: datetime
    run_finished_at: datetime
    ragas_judge_model: str
    cases: list[EvaluationCase]
    summary: EvaluationSummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "chatbot_id": str(self.chatbot_id),
            "chatbot_name": self.chatbot_name,
            "dataset_path": self.dataset_path,
            "scenario_filter": self.scenario_filter,
            "run_started_at": self.run_started_at.isoformat(),
            "run_finished_at": self.run_finished_at.isoformat(),
            "ragas_judge_model": self.ragas_judge_model,
            "cases": [c.to_dict() for c in self.cases],
            "summary": self.summary.to_dict(),
        }

    def top_failures(self, *, metric: str, n: int = 3) -> list[EvaluationCase]:
        """Return the ``n`` scored cases with the lowest score on ``metric``.

        Errored cases are excluded. Cases missing this metric are excluded.
        Used by the Markdown report to flag worst offenders per metric.
        """
        candidates = [
            c for c in self.cases
            if c.error is None and c.scores and metric in c.scores
        ]
        candidates.sort(key=lambda c: c.scores[metric])  # type: ignore[index]
        return candidates[:n]
```

- [ ] **Step 1.10: Run report VO tests, expect 4 PASSED**

```bash
pytest tests/unit/test_evaluation_report_vo.py -v
```

Expected: **4 PASSED**.

- [ ] **Step 1.11: Create `backend/src/tfm_rag/domain/errors/evaluation.py`**

```python
from tfm_rag.domain.errors.common import DomainError


class EvaluationDatasetError(DomainError):
    """Raised when an evaluation dataset cannot be loaded (file missing,
    malformed JSONL, missing required fields, etc.). The CLI surfaces this
    as a non-zero exit + stderr message.
    """


class EvaluationError(DomainError):
    """Raised when the evaluation pipeline fails for a non-dataset reason
    (RAGAS crash, no scored cases, judge LLM unreachable, etc.).
    """
```

- [ ] **Step 1.12: Write failing tests for the dataset loader**

Create `backend/tests/unit/test_dataset_loader.py`:

```python
import json
from pathlib import Path

import pytest

from tfm_rag.application.evaluation.dataset_loader import (
    load_evaluation_dataset,
)
from tfm_rag.domain.errors.evaluation import EvaluationDatasetError


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


def test_load_dataset_returns_evaluation_cases(tmp_path: Path) -> None:
    p = tmp_path / "ds.jsonl"
    _write_jsonl(p, [
        {
            "question": "Q1?",
            "ground_truth": "GT1",
            "scenario": "doc_only",
            "metadata": {"difficulty": "easy"},
        },
        {
            "question": "Q2?",
            "ground_truth": "GT2",
            "scenario": "abstain",
        },  # metadata is optional
    ])
    cases = load_evaluation_dataset(p)
    assert len(cases) == 2
    assert cases[0].question == "Q1?"
    assert cases[0].scenario == "doc_only"
    assert cases[0].metadata == {"difficulty": "easy"}
    assert cases[1].metadata == {}


def test_load_dataset_filters_by_scenario(tmp_path: Path) -> None:
    p = tmp_path / "ds.jsonl"
    _write_jsonl(p, [
        {"question": "Q1?", "ground_truth": "gt", "scenario": "doc_only"},
        {"question": "Q2?", "ground_truth": "gt", "scenario": "abstain"},
        {"question": "Q3?", "ground_truth": "gt", "scenario": "doc_only"},
    ])
    cases = load_evaluation_dataset(p, scenario_filter="doc_only")
    assert len(cases) == 2
    assert all(c.scenario == "doc_only" for c in cases)


def test_load_dataset_skips_blank_lines(tmp_path: Path) -> None:
    p = tmp_path / "ds.jsonl"
    p.write_text(
        '{"question":"Q?", "ground_truth":"gt", "scenario":"doc_only"}\n'
        "\n"  # blank
        "   \n"  # whitespace-only
        '{"question":"Q2?", "ground_truth":"gt", "scenario":"doc_only"}\n',
        encoding="utf-8",
    )
    cases = load_evaluation_dataset(p)
    assert len(cases) == 2


def test_load_dataset_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(EvaluationDatasetError, match="does not exist"):
        load_evaluation_dataset(tmp_path / "missing.jsonl")


def test_load_dataset_malformed_json_raises_with_line_number(
    tmp_path: Path,
) -> None:
    p = tmp_path / "ds.jsonl"
    p.write_text(
        '{"question":"ok", "ground_truth":"gt", "scenario":"doc_only"}\n'
        "{this is not json}\n",
        encoding="utf-8",
    )
    with pytest.raises(EvaluationDatasetError, match="line 2"):
        load_evaluation_dataset(p)


def test_load_dataset_missing_required_field_raises(tmp_path: Path) -> None:
    p = tmp_path / "ds.jsonl"
    p.write_text(
        '{"question":"missing gt", "scenario":"doc_only"}\n',
        encoding="utf-8",
    )
    with pytest.raises(EvaluationDatasetError, match="ground_truth"):
        load_evaluation_dataset(p)
```

- [ ] **Step 1.13: Create `backend/src/tfm_rag/application/evaluation/__init__.py`**

Empty package marker:

```python
```

- [ ] **Step 1.14: Create `backend/src/tfm_rag/application/evaluation/dataset_loader.py`**

```python
import json
from pathlib import Path
from typing import Any

from tfm_rag.domain.errors.evaluation import EvaluationDatasetError
from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase

_REQUIRED_FIELDS = ("question", "ground_truth", "scenario")


def _parse_line(line_no: int, raw: str) -> dict[str, Any]:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EvaluationDatasetError(
            f"Malformed JSON on line {line_no}: {exc.msg}"
        ) from exc
    if not isinstance(obj, dict):
        raise EvaluationDatasetError(
            f"Line {line_no}: expected a JSON object, got {type(obj).__name__}"
        )
    for field in _REQUIRED_FIELDS:
        if field not in obj:
            raise EvaluationDatasetError(
                f"Line {line_no}: missing required field {field!r}"
            )
    return obj


def load_evaluation_dataset(
    path: Path,
    *,
    scenario_filter: str | None = None,
) -> list[EvaluationCase]:
    """Read a JSONL evaluation dataset.

    Each non-blank line must be a JSON object with at least
    ``question``, ``ground_truth``, ``scenario``. ``metadata`` is
    optional (defaults to ``{}``).

    ``scenario_filter``: if set, only entries with matching ``scenario``
    are kept.

    Raises ``EvaluationDatasetError`` for missing files, malformed JSON
    (with line number), or entries missing required fields.
    """
    path = Path(path)
    if not path.exists():
        raise EvaluationDatasetError(f"Dataset file does not exist: {path}")

    cases: list[EvaluationCase] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            if not raw.strip():
                continue
            obj = _parse_line(line_no, raw)
            case = EvaluationCase(
                question=str(obj["question"]),
                ground_truth=str(obj["ground_truth"]),
                scenario=str(obj["scenario"]),
                metadata=dict(obj.get("metadata") or {}),
            )
            if scenario_filter and case.scenario != scenario_filter:
                continue
            cases.append(case)
    return cases
```

- [ ] **Step 1.15: Run dataset loader tests, expect 6 PASSED**

```bash
pytest tests/unit/test_dataset_loader.py -v
```

Expected: **6 PASSED**.

- [ ] **Step 1.16: Run all Task 1 tests together, expect 17 PASSED**

```bash
pytest tests/unit/test_eval_scenarios.py tests/unit/test_evaluation_case_vo.py tests/unit/test_evaluation_report_vo.py tests/unit/test_dataset_loader.py -v
```

Expected: **17 PASSED** (3 + 4 + 4 + 6).

- [ ] **Step 1.17: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/domain/catalog/eval_scenarios.py backend/src/tfm_rag/domain/value_objects/evaluation_case.py backend/src/tfm_rag/domain/value_objects/evaluation_report.py backend/src/tfm_rag/domain/errors/evaluation.py backend/src/tfm_rag/application/evaluation/__init__.py backend/src/tfm_rag/application/evaluation/dataset_loader.py backend/tests/unit/test_eval_scenarios.py backend/tests/unit/test_evaluation_case_vo.py backend/tests/unit/test_evaluation_report_vo.py backend/tests/unit/test_dataset_loader.py
git commit -m "feat(eval): EvaluationCase + EvaluationReport VOs + scenarios catalog + JSONL loader"
```

---

## Task 2 — Extend `answer_query` with `persist` flag + `retrieved_contexts`

Plan #15's agent loop persists every turn to `chat_sessions` / `chat_messages` and exposes citations + iterations on `AnswerView`. Evaluation needs neither persistence (we don't want eval runs polluting history) nor a re-query of Qdrant to recover the chunk texts for RAGAS. This task adds two affordances — both backwards-compatible defaults.

**Files:**
- Modify: `backend/src/tfm_rag/application/chat/answer_query.py`
- Create: `backend/tests/unit/test_answer_query_persist_and_contexts.py`

- [ ] **Step 2.1: Write failing tests for the new behaviour**

Create `backend/tests/unit/test_answer_query_persist_and_contexts.py`:

```python
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tfm_rag.application.chat.answer_query import answer_query
from tfm_rag.domain.catalog.agent_tools import (
    TOOL_FINAL_ANSWER,
    TOOL_SEARCH_DOCS,
)
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.retrieval_iteration import LLMToolCall
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk
from tfm_rag.infrastructure.persistence.repository import RequestContext


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), user_id=uuid4())


def _chunk(text: str, idx: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        point_id=f"pid-{idx}",
        content=text,
        source_id=uuid4(),
        source_filename="manual.pdf",
        chunk_index=idx,
        score=0.9,
        metadata={},
    )


def _chatbot_row(tenant_id) -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.tenant_id = tenant_id
    row.name = "Bot"
    row.description = None
    row.system_prompt = "be terse"
    row.llm_selection = {
        "provider_id": "ollama",
        "credential_id": str(uuid4()),
        "model_id": "llama3.1",
    }
    row.pipeline_config = PipelineConfig.default().to_dict()
    row.widget_config = {}
    return row


def _chatbot_repo(row) -> MagicMock:
    repo = MagicMock()
    repo.get = AsyncMock(return_value=row)
    repo.list_kb_ids = AsyncMock(return_value=[uuid4()])
    return repo


def _fake_settings() -> MagicMock:
    s = MagicMock()
    s.ollama_base_url = "http://ollama:11434"
    return s


class _ScriptedLLM:
    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._script.pop(0)


@pytest.mark.asyncio
async def test_retrieved_contexts_populated_from_search_results() -> None:
    """AnswerView.retrieved_contexts contains the content of every chunk
    seen across the loop (in seen_chunks insertion order).
    """
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_SEARCH_DOCS, arguments={"query": "q"}),
        LLMToolCall(tool=TOOL_FINAL_ANSWER, arguments={"answer": "ok"}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    chunks = [_chunk("alpha", 0), _chunk("beta", 1)]

    async def fake_retrieve(*args: Any, **kwargs: Any) -> Any:
        return chunks

    async def fake_create(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_append(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        return None

    view = await answer_query(
        MagicMock(), ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: MagicMock(),
        llm_dispatcher=dispatcher,
        retrieve_docs=fake_retrieve,
        create_session=fake_create,
        append_message=fake_append,
        touch_session=fake_touch,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        settings=_fake_settings(),
        chatbot_id=row.id,
        session_id=None,
        user_message="?",
    )
    assert view.retrieved_contexts == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_retrieved_contexts_dedup_by_point_id() -> None:
    """If two search calls return overlapping chunks, retrieved_contexts
    contains each chunk's content only once (dedup mirrors citations).
    """
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    shared = _chunk("shared", 0)
    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_SEARCH_DOCS, arguments={"query": "q1"}),
        LLMToolCall(tool=TOOL_SEARCH_DOCS, arguments={"query": "q2"}),
        LLMToolCall(tool=TOOL_FINAL_ANSWER, arguments={"answer": "ok"}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    results = [[shared], [shared]]

    async def fake_retrieve(*args: Any, **kwargs: Any) -> Any:
        return results.pop(0)

    async def fake_pass(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_void(*args: Any, **kwargs: Any) -> None:
        return None

    view = await answer_query(
        MagicMock(), ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: MagicMock(),
        llm_dispatcher=dispatcher,
        retrieve_docs=fake_retrieve,
        create_session=fake_pass,
        append_message=fake_pass,
        touch_session=fake_void,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        settings=_fake_settings(),
        chatbot_id=row.id,
        session_id=None,
        user_message="?",
    )
    assert view.retrieved_contexts == ["shared"]


@pytest.mark.asyncio
async def test_persist_false_skips_session_and_message_persistence() -> None:
    """When persist=False, create_session / append_message / touch_session
    must NOT be called. The AnswerView still has a (throwaway) session_id
    and message_id so callers don't need to deal with Optional types.
    """
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_FINAL_ANSWER, arguments={"answer": "ok"}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    create_calls = 0
    append_calls = 0
    touch_calls = 0

    async def fake_create(*args: Any, **kwargs: Any) -> Any:
        nonlocal create_calls
        create_calls += 1
        return uuid4()

    async def fake_append(*args: Any, **kwargs: Any) -> Any:
        nonlocal append_calls
        append_calls += 1
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        nonlocal touch_calls
        touch_calls += 1

    view = await answer_query(
        MagicMock(), ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: MagicMock(),
        llm_dispatcher=dispatcher,
        retrieve_docs=AsyncMock(return_value=[]),
        create_session=fake_create,
        append_message=fake_append,
        touch_session=fake_touch,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        settings=_fake_settings(),
        chatbot_id=row.id,
        session_id=None,
        user_message="x",
        persist=False,
    )
    assert create_calls == 0
    assert append_calls == 0
    assert touch_calls == 0
    assert view.content == "ok"
    # Throwaway UUIDs are still returned (so AnswerView's types stay clean).
    assert view.session_id is not None
    assert view.message_id is not None


@pytest.mark.asyncio
async def test_persist_true_default_still_persists() -> None:
    """Regression guard: default behaviour (persist=True) must remain the
    same as plan #15 — create_session called when no session_id, then
    two append_message + one touch.
    """
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_FINAL_ANSWER, arguments={"answer": "ok"}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    create_calls = 0
    append_calls = 0
    touch_calls = 0

    async def fake_create(*args: Any, **kwargs: Any) -> Any:
        nonlocal create_calls
        create_calls += 1
        return uuid4()

    async def fake_append(*args: Any, **kwargs: Any) -> Any:
        nonlocal append_calls
        append_calls += 1
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        nonlocal touch_calls
        touch_calls += 1

    await answer_query(
        MagicMock(), ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: MagicMock(),
        llm_dispatcher=dispatcher,
        retrieve_docs=AsyncMock(return_value=[]),
        create_session=fake_create,
        append_message=fake_append,
        touch_session=fake_touch,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        settings=_fake_settings(),
        chatbot_id=row.id,
        session_id=None,
        user_message="x",
    )
    assert create_calls == 1
    assert append_calls == 2   # user + assistant
    assert touch_calls == 1
```

- [ ] **Step 2.2: Run, confirm 3 failures + 1 pass (the regression-guard test should already pass; the other 3 fail)**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pytest tests/unit/test_answer_query_persist_and_contexts.py -v
```

Expected: 3 failures (retrieved_contexts and persist=False tests) + 1 pass (regression guard). If even the regression guard fails, **stop and investigate** — plan #15 may have regressed.

- [ ] **Step 2.3: Modify `backend/src/tfm_rag/application/chat/answer_query.py` — extend `AnswerView`**

Add `retrieved_contexts` field. Find the `AnswerView` dataclass (around the top of the file, after the type aliases) and modify it to:

```python
@dataclass(frozen=True, slots=True)
class AnswerView:
    session_id: UUID
    message_id: UUID
    content: str
    citations: list[Citation]
    iterations: list[RetrievalIteration]
    retrieved_contexts: list[str] = field(default_factory=list, hash=False)
```

(Add `field` to the existing `from dataclasses import dataclass` import if it isn't already imported. The plan #15 file imports `field` already from `dataclasses` indirectly via use elsewhere — verify before editing.)

- [ ] **Step 2.4: Modify `answer_query` to accept `persist` and build `retrieved_contexts`**

The function signature should grow one new kwarg, **at the end of the keyword arguments**, with default `True`:

```python
async def answer_query(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    kb_repo_factory: KbRepoFactory = _default_kb_repo,
    llm_dispatcher: LLMDispatcher,
    retrieve_docs: RetrieveDocs = _real_retrieve_docs,
    create_session: CreateSession = _real_create_session,
    append_message: AppendMessage = _real_append_message,
    touch_session: TouchSession = _real_touch_session,
    qdrant: QdrantStore,
    embedder_dispatcher: EmbedderDispatcher,
    settings: Settings,
    chatbot_id: UUID,
    session_id: UUID | None,
    user_message: str,
    persist: bool = True,
) -> AnswerView:
```

Then update the body. Locate the three persistence call sites and gate them:

**Site 1 — Step 2 (ensure session)**: replace

```python
    if session_id is None:
        session_id = await create_session(
            session, ctx,
            chatbot_id=chatbot_id,
            origin="playground",
            public_session_cookie=None,
        )
```

with

```python
    from uuid import uuid4 as _uuid4  # local — keep existing top-level imports untouched
    if session_id is None:
        if persist:
            session_id = await create_session(
                session, ctx,
                chatbot_id=chatbot_id,
                origin="playground",
                public_session_cookie=None,
            )
        else:
            # Throwaway UUID — no DB row exists. The eval flow doesn't read
            # session_id off the view, but we keep the type non-Optional so
            # the HTTP path doesn't have to deal with None.
            session_id = _uuid4()
```

**Site 2 — Step 3 (append user msg)**: wrap

```python
    await append_message(
        session, ctx,
        session_id=session_id,
        role="user",
        content=user_message,
        citations=None,
        metadata=None,
    )
```

with `if persist:`:

```python
    if persist:
        await append_message(
            session, ctx,
            session_id=session_id,
            role="user",
            content=user_message,
            citations=None,
            metadata=None,
        )
```

**Site 3 — Step 6 (append assistant msg)**: replace

```python
    metadata = {"iterations": [it.to_dict() for it in iterations]}
    message_id = await append_message(
        session, ctx,
        session_id=session_id,
        role="assistant",
        content=assistant_content,
        citations=[c.to_dict() for c in citations],
        metadata=metadata,
    )
```

with

```python
    metadata = {"iterations": [it.to_dict() for it in iterations]}
    if persist:
        message_id = await append_message(
            session, ctx,
            session_id=session_id,
            role="assistant",
            content=assistant_content,
            citations=[c.to_dict() for c in citations],
            metadata=metadata,
        )
    else:
        message_id = _uuid4()
```

**Site 4 — Step 7 (touch)**: wrap

```python
    await touch_session(session, ctx, session_id=session_id)
```

with `if persist:`:

```python
    if persist:
        await touch_session(session, ctx, session_id=session_id)
```

**Site 5 — Build retrieved_contexts and pass it to AnswerView**. Find the final `return AnswerView(...)` and modify it:

```python
    return AnswerView(
        session_id=session_id,
        message_id=message_id,
        content=assistant_content,
        citations=citations,
        iterations=iterations,
        retrieved_contexts=[c.content for c in seen_chunks.values()],
    )
```

- [ ] **Step 2.5: Run the new tests, expect 4 PASSED**

```bash
pytest tests/unit/test_answer_query_persist_and_contexts.py -v
```

Expected: **4 PASSED**.

- [ ] **Step 2.6: Run the existing plan #15 tests to confirm no regression, expect 7 PASSED**

```bash
pytest tests/unit/test_answer_query.py -v
```

Expected: **7 PASSED**. The `field(default_factory=list)` default makes the new field invisible to existing tests.

- [ ] **Step 2.7: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/application/chat/answer_query.py backend/tests/unit/test_answer_query_persist_and_contexts.py
git commit -m "feat(chat): AnswerView.retrieved_contexts + answer_query(persist=...) for eval"
```

---

## Task 3 — Infrastructure: RAGAS evaluator adapter + `eval` extras

**Files:**
- Modify: `backend/pyproject.toml` (add `[project.optional-dependencies].eval` + `[project.scripts]`)
- Create: `backend/src/tfm_rag/infrastructure/evaluation/__init__.py`
- Create: `backend/src/tfm_rag/infrastructure/evaluation/ragas_evaluator.py`
- Create: `backend/tests/unit/test_ragas_evaluator.py`

- [ ] **Step 3.1: Add the `eval` extras and CLI script to `backend/pyproject.toml`**

Modify the file. After the existing `[project.optional-dependencies].dev` block, add an `eval` extras block; and add a `[project.scripts]` table after the `[build-system]` block. The final relevant section should read:

```toml
[project]
name = "tfm-rag-backend"
version = "0.1.0"
description = "TFM RAG Chatbot Platform — backend"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic[email]>=2.9",
    "pydantic-settings>=2.6",
    "python-jose[cryptography]>=3.3",
    "sqlalchemy[asyncio]>=2.0.36",
    "alembic>=1.14",
    "asyncpg>=0.30",
    "qdrant-client>=1.12",
    "pypdf>=5.1",
    "python-multipart>=0.0.9",
    "httpx>=0.28",
    "structlog>=24.4",
    "bcrypt>=4.2",
    "google-auth>=2.35",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-cov>=6.0",
    "testcontainers>=4.8",
    "ruff>=0.8",
    "mypy>=1.13",
]
eval = [
    "ragas>=0.2",
    "langchain-ollama>=0.2",
    "langchain-community>=0.3",
    "datasets>=3.0",
]

[project.scripts]
eval-ragas = "tfm_rag.cli.eval_ragas:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tfm_rag"]
```

- [ ] **Step 3.2: Install the eval extras into the venv**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pip install -e '.[eval,dev]'
```

Expected: pip pulls down ragas + langchain-ollama + langchain-community + datasets + transitive deps. Should finish in 1-3 minutes. Verify with:

```bash
python -c "import ragas; from langchain_ollama import OllamaLLM, OllamaEmbeddings; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3.3: Write failing tests for `RagasEvaluator`**

Create `backend/tests/unit/test_ragas_evaluator.py`:

```python
"""Unit tests for RagasEvaluator with the ragas library stubbed.

We don't call the real RAGAS in unit tests (it would hit a real LLM,
slow + flaky). Instead we mock `ragas.evaluate` and the langchain
wrappers to verify our adapter:
- builds the right ragas EvaluationDataset
- passes the right metrics
- maps ragas results back onto EvaluationCase.scores
"""
from unittest.mock import MagicMock, patch

from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase
from tfm_rag.infrastructure.evaluation.ragas_evaluator import (
    RagasEvaluator,
    RagasMetric,
)


def _case(question: str, answer: str, contexts: list[str], gt: str) -> EvaluationCase:
    return EvaluationCase(
        question=question,
        ground_truth=gt,
        scenario="doc_only",
        metadata={},
        predicted_answer=answer,
        retrieved_contexts=contexts,
        citations=[],
        iterations=[],
    )


def test_ragas_metric_constants_match_ragas_internal_names() -> None:
    """The metric names we expose to callers map 1:1 to RAGAS internal
    column names. This guards against ragas renaming a metric without us
    noticing (the integration test would fail with a missing column).
    """
    assert RagasMetric.FAITHFULNESS == "faithfulness"
    assert RagasMetric.ANSWER_RELEVANCY == "answer_relevancy"
    assert RagasMetric.CONTEXT_PRECISION == "context_precision"
    assert RagasMetric.CONTEXT_RECALL == "context_recall"


@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.evaluate")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainLLMWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainEmbeddingsWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaLLM")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaEmbeddings")
def test_evaluator_calls_ragas_with_expected_dataset(
    mock_emb_cls,
    mock_llm_cls,
    mock_emb_wrapper,
    mock_llm_wrapper,
    mock_evaluate,
) -> None:
    # Mock RAGAS result: pandas-like object with .to_pandas() → DataFrame.
    fake_result = MagicMock()
    fake_df = MagicMock()
    fake_df.to_dict.return_value = {
        "faithfulness": {0: 0.8, 1: 0.6},
        "answer_relevancy": {0: 0.9, 1: 0.7},
        "context_precision": {0: 0.85, 1: 0.55},
        "context_recall": {0: 0.75, 1: 0.5},
    }
    fake_result.to_pandas.return_value = fake_df
    mock_evaluate.return_value = fake_result

    cases = [
        _case("Q1?", "A1.", ["ctx1"], "GT1"),
        _case("Q2?", "A2.", ["ctx2a", "ctx2b"], "GT2"),
    ]

    evaluator = RagasEvaluator(
        base_url="http://ollama:11434",
        judge_model="llama3.1",
        embedding_model="bge-m3",
    )
    scores = evaluator.evaluate(cases)

    # ragas.evaluate was called once
    mock_evaluate.assert_called_once()
    kwargs = mock_evaluate.call_args.kwargs
    # The dataset shape matches the ragas 0.2 convention
    assert "dataset" in kwargs
    assert "metrics" in kwargs
    # We pass exactly the 4 metrics
    metric_names = {m.name for m in kwargs["metrics"]}
    assert metric_names == {
        "faithfulness", "answer_relevancy",
        "context_precision", "context_recall",
    }
    # Returned shape: list of dicts (per case)
    assert len(scores) == 2
    assert scores[0]["faithfulness"] == 0.8
    assert scores[1]["faithfulness"] == 0.6


@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.evaluate")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainLLMWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainEmbeddingsWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaLLM")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaEmbeddings")
def test_evaluator_skips_cases_with_errors_or_no_contexts(
    mock_emb_cls,
    mock_llm_cls,
    mock_emb_wrapper,
    mock_llm_wrapper,
    mock_evaluate,
) -> None:
    """Cases with .error set or empty retrieved_contexts can't be scored
    (RAGAS needs both contexts AND an answer). The adapter skips them and
    returns an empty score-dict for those positions, preserving alignment.
    """
    fake_result = MagicMock()
    fake_result.to_pandas.return_value.to_dict.return_value = {
        "faithfulness": {0: 0.7},
        "answer_relevancy": {0: 0.8},
        "context_precision": {0: 0.8},
        "context_recall": {0: 0.6},
    }
    mock_evaluate.return_value = fake_result

    good = _case("Q1?", "A1.", ["ctx1"], "GT1")
    err = _case("Q2?", "A2.", ["ctx2"], "GT2")
    err.error = "LLM timeout"
    no_ctx = _case("Q3?", "A3.", [], "GT3")

    evaluator = RagasEvaluator(
        base_url="http://ollama:11434",
        judge_model="llama3.1",
        embedding_model="bge-m3",
    )
    scores = evaluator.evaluate([good, err, no_ctx])

    # Three positions returned to keep alignment; only the good one has scores
    assert len(scores) == 3
    assert scores[0]["faithfulness"] == 0.7
    assert scores[1] == {}
    assert scores[2] == {}


@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.evaluate")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainLLMWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainEmbeddingsWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaLLM")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaEmbeddings")
def test_evaluator_with_zero_scorable_cases_returns_empty_dicts(
    mock_emb_cls,
    mock_llm_cls,
    mock_emb_wrapper,
    mock_llm_wrapper,
    mock_evaluate,
) -> None:
    """If no cases are scorable, ragas.evaluate is never called and we
    return a same-length list of empty dicts.
    """
    err = _case("Q?", "A", ["c"], "gt")
    err.error = "boom"
    no_ctx = _case("Q?", "A", [], "gt")

    evaluator = RagasEvaluator(
        base_url="http://ollama:11434",
        judge_model="llama3.1",
        embedding_model="bge-m3",
    )
    scores = evaluator.evaluate([err, no_ctx])

    mock_evaluate.assert_not_called()
    assert scores == [{}, {}]


def test_judge_model_attribute_exposed() -> None:
    """The CLI / report writer reads `evaluator.judge_model` to record it
    in the EvaluationReport. Guard this minimal surface.
    """
    evaluator = RagasEvaluator(
        base_url="http://ollama:11434",
        judge_model="custom-model",
        embedding_model="bge-m3",
    )
    assert evaluator.judge_model == "custom-model"
```

- [ ] **Step 3.4: Run, confirm collection failure**

```bash
pytest tests/unit/test_ragas_evaluator.py -v
```

Expected: collection error — `ragas_evaluator` module doesn't exist.

- [ ] **Step 3.5: Create `backend/src/tfm_rag/infrastructure/evaluation/__init__.py`**

Empty file (package marker).

- [ ] **Step 3.6: Create `backend/src/tfm_rag/infrastructure/evaluation/ragas_evaluator.py`**

```python
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
        # Filter to scorable cases (preserve indices so we can re-align).
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

        # Initialise the output with empty dicts in every position
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
        # as_dict has shape: {metric_name: {row_index: score}}
        for metric_name in (
            RagasMetric.FAITHFULNESS,
            RagasMetric.ANSWER_RELEVANCY,
            RagasMetric.CONTEXT_PRECISION,
            RagasMetric.CONTEXT_RECALL,
        ):
            metric_col = as_dict.get(metric_name, {})
            for row_idx_str, value in metric_col.items():
                # pandas df may key by int or str; normalise
                row_idx = (
                    int(row_idx_str) if not isinstance(row_idx_str, int)
                    else row_idx_str
                )
                if row_idx < 0 or row_idx >= len(rows):
                    continue
                global_idx = scorable_indices[row_idx]
                if value is None or (isinstance(value, float) and value != value):
                    # NaN — RAGAS returns NaN when a metric fails for a case
                    continue
                out[global_idx][metric_name] = float(value)
        return out
```

- [ ] **Step 3.7: Run the evaluator tests, expect 5 PASSED**

```bash
pytest tests/unit/test_ragas_evaluator.py -v
```

Expected: **5 PASSED**.

- [ ] **Step 3.8: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/pyproject.toml backend/src/tfm_rag/infrastructure/evaluation/__init__.py backend/src/tfm_rag/infrastructure/evaluation/ragas_evaluator.py backend/tests/unit/test_ragas_evaluator.py
git commit -m "feat(eval): RagasEvaluator adapter (ragas + langchain-ollama) + eval extras"
```

---

## Task 4 — Application use case `run_ragas_evaluation` + report writer

**Files:**
- Create: `backend/src/tfm_rag/application/evaluation/report_writer.py`
- Create: `backend/src/tfm_rag/application/evaluation/run_ragas_evaluation.py`
- Create: `backend/tests/unit/test_report_writer.py`
- Create: `backend/tests/unit/test_run_ragas_evaluation.py`

- [ ] **Step 4.1: Write failing tests for the report writer**

Create `backend/tests/unit/test_report_writer.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tfm_rag.application.evaluation.report_writer import write_report
from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase
from tfm_rag.domain.value_objects.evaluation_report import (
    EvaluationReport,
    EvaluationSummary,
)


def _report(cases: list[EvaluationCase]) -> EvaluationReport:
    when = datetime(2026, 5, 24, 10, 0, tzinfo=timezone.utc)
    return EvaluationReport(
        chatbot_id=uuid4(),
        chatbot_name="HistoryBot",
        dataset_path="/tmp/ds.jsonl",
        scenario_filter="doc_only",
        run_started_at=when,
        run_finished_at=when,
        ragas_judge_model="llama3.1",
        cases=cases,
        summary=EvaluationSummary.from_cases(cases),
    )


def _scored(q: str, f: float, ar: float, cp: float, cr: float) -> EvaluationCase:
    return EvaluationCase(
        question=q, ground_truth="gt", scenario="doc_only", metadata={},
        predicted_answer="a", retrieved_contexts=["c"],
        scores={
            "faithfulness": f,
            "answer_relevancy": ar,
            "context_precision": cp,
            "context_recall": cr,
        },
    )


def test_write_report_emits_report_json_and_md(tmp_path: Path) -> None:
    cases = [_scored("Q1?", 0.8, 0.9, 0.8, 0.7), _scored("Q2?", 0.5, 0.6, 0.5, 0.4)]
    report = _report(cases)

    paths = write_report(report, output_dir=tmp_path)

    assert paths.json_path.exists()
    assert paths.markdown_path.exists()
    assert paths.json_path.name == "report.json"
    assert paths.markdown_path.name == "report.md"

    data = json.loads(paths.json_path.read_text(encoding="utf-8"))
    assert data["chatbot_name"] == "HistoryBot"
    assert data["summary"]["num_cases"] == 2
    assert len(data["cases"]) == 2


def test_markdown_report_contains_summary_table(tmp_path: Path) -> None:
    cases = [_scored("Q?", 0.7, 0.8, 0.6, 0.5)]
    report = _report(cases)
    paths = write_report(report, output_dir=tmp_path)

    md = paths.markdown_path.read_text(encoding="utf-8")
    # Header
    assert "# Evaluation report" in md
    # Metrics summary table
    assert "| Metric | Score |" in md
    assert "faithfulness" in md
    assert "answer_relevancy" in md


def test_markdown_report_includes_top_failures(tmp_path: Path) -> None:
    cases = [
        _scored("Q1?", 0.9, 0.9, 0.8, 0.7),
        _scored("Q2?", 0.2, 0.4, 0.3, 0.2),
        _scored("Q3?", 0.5, 0.6, 0.5, 0.4),
    ]
    report = _report(cases)
    paths = write_report(report, output_dir=tmp_path)

    md = paths.markdown_path.read_text(encoding="utf-8")
    # Top failures section exists for each metric
    assert "## Top failures by faithfulness" in md
    # Q2 should appear (lowest faithfulness score)
    assert "Q2?" in md


def test_write_report_creates_output_dir_if_missing(tmp_path: Path) -> None:
    deep_dir = tmp_path / "a" / "b" / "c"
    assert not deep_dir.exists()
    cases = [_scored("Q?", 0.5, 0.5, 0.5, 0.5)]
    report = _report(cases)
    paths = write_report(report, output_dir=deep_dir)
    assert deep_dir.exists()
    assert paths.json_path.exists()
```

- [ ] **Step 4.2: Run, confirm collection failure**

```bash
pytest tests/unit/test_report_writer.py -v
```

Expected: collection error.

- [ ] **Step 4.3: Create `backend/src/tfm_rag/application/evaluation/report_writer.py`**

```python
import json
from dataclasses import dataclass
from pathlib import Path

from tfm_rag.domain.value_objects.evaluation_report import EvaluationReport
from tfm_rag.infrastructure.evaluation.ragas_evaluator import RagasMetric


@dataclass(frozen=True, slots=True)
class ReportPaths:
    json_path: Path
    markdown_path: Path


_REPORTED_METRICS = (
    RagasMetric.FAITHFULNESS,
    RagasMetric.ANSWER_RELEVANCY,
    RagasMetric.CONTEXT_PRECISION,
    RagasMetric.CONTEXT_RECALL,
)


def _format_markdown(report: EvaluationReport) -> str:
    lines: list[str] = []
    lines.append(f"# Evaluation report — {report.chatbot_name}")
    lines.append("")
    lines.append(f"- Chatbot ID: `{report.chatbot_id}`")
    lines.append(f"- Dataset: `{report.dataset_path}`")
    lines.append(f"- Scenario filter: `{report.scenario_filter or '*'}`")
    lines.append(f"- Judge model: `{report.ragas_judge_model}`")
    lines.append(f"- Run start: `{report.run_started_at.isoformat()}`")
    lines.append(f"- Run end: `{report.run_finished_at.isoformat()}`")
    lines.append("")
    lines.append(
        f"**Cases:** {report.summary.num_cases} total, "
        f"{report.summary.num_scored} scored, "
        f"{report.summary.num_errors} errored."
    )
    lines.append("")
    lines.append("## Summary metrics")
    lines.append("")
    lines.append("| Metric | Score |")
    lines.append("| --- | --- |")
    for metric in _REPORTED_METRICS:
        value = report.summary.metrics.get(metric)
        cell = f"{value:.3f}" if value is not None else "—"
        lines.append(f"| {metric} | {cell} |")
    lines.append("")

    for metric in _REPORTED_METRICS:
        top = report.top_failures(metric=metric, n=3)
        if not top:
            continue
        lines.append(f"## Top failures by {metric}")
        lines.append("")
        for case in top:
            score = (case.scores or {}).get(metric)
            score_cell = f"{score:.3f}" if score is not None else "—"
            preview = case.predicted_answer or "(no answer)"
            if len(preview) > 200:
                preview = preview[:200] + "..."
            lines.append(f"- **{score_cell}** — _Q:_ {case.question}")
            lines.append(f"  - GT: {case.ground_truth}")
            lines.append(f"  - A: {preview}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_report(
    report: EvaluationReport,
    *,
    output_dir: Path,
) -> ReportPaths:
    """Serialise a report to ``output_dir``: ``report.json`` (machine) +
    ``report.md`` (human). Creates ``output_dir`` if it doesn't exist.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"

    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(_format_markdown(report), encoding="utf-8")
    return ReportPaths(json_path=json_path, markdown_path=md_path)
```

- [ ] **Step 4.4: Run report writer tests, expect 4 PASSED**

```bash
pytest tests/unit/test_report_writer.py -v
```

Expected: **4 PASSED**.

- [ ] **Step 4.5: Write failing tests for `run_ragas_evaluation`**

Create `backend/tests/unit/test_run_ragas_evaluation.py`:

```python
"""Unit tests for the run_ragas_evaluation orchestrator.

We fake answer_query (no real LLM call), fake the RagasEvaluator (no
real ragas call), and verify the use case wires them together correctly.
"""
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tfm_rag.application.evaluation.run_ragas_evaluation import (
    run_ragas_evaluation,
)
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.evaluation import EvaluationError
from tfm_rag.infrastructure.persistence.repository import RequestContext


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), user_id=uuid4())


def _chatbot_row(tenant_id, name: str = "Bot") -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.tenant_id = tenant_id
    row.name = name
    return row


def _write_dataset(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "ds.jsonl"
    p.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    return p


def _answer_view(answer: str, contexts: list[str]) -> MagicMock:
    av = MagicMock()
    av.content = answer
    av.retrieved_contexts = contexts
    av.citations = []
    av.iterations = []
    av.session_id = uuid4()
    av.message_id = uuid4()
    return av


@pytest.mark.asyncio
async def test_runs_each_case_and_returns_scored_report(
    tmp_path: Path,
) -> None:
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(return_value=row)

    dataset_path = _write_dataset(tmp_path, [
        {"question": "Q1?", "ground_truth": "GT1", "scenario": "doc_only"},
        {"question": "Q2?", "ground_truth": "GT2", "scenario": "doc_only"},
    ])

    answers = [
        _answer_view("A1", ["ctx1"]),
        _answer_view("A2", ["ctx2"]),
    ]
    call_count = 0

    async def fake_answer_query(*args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        result = answers[call_count]
        call_count += 1
        return result

    # Evaluator returns per-case scores
    fake_evaluator = MagicMock()
    fake_evaluator.judge_model = "llama3.1"
    fake_evaluator.evaluate = MagicMock(
        return_value=[
            {"faithfulness": 0.8, "answer_relevancy": 0.9,
             "context_precision": 0.8, "context_recall": 0.7},
            {"faithfulness": 0.6, "answer_relevancy": 0.7,
             "context_precision": 0.6, "context_recall": 0.5},
        ]
    )

    report = await run_ragas_evaluation(
        MagicMock(), ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        answer_query=fake_answer_query,
        evaluator=fake_evaluator,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        llm_dispatcher=MagicMock(),
        settings=MagicMock(),
        chatbot_id=row.id,
        dataset_path=dataset_path,
        scenario_filter=None,
    )

    assert report.chatbot_name == "Bot"
    assert report.ragas_judge_model == "llama3.1"
    assert len(report.cases) == 2
    assert report.cases[0].predicted_answer == "A1"
    assert report.cases[0].retrieved_contexts == ["ctx1"]
    assert report.cases[0].scores["faithfulness"] == 0.8
    assert report.summary.num_scored == 2
    assert call_count == 2


@pytest.mark.asyncio
async def test_filters_by_scenario(tmp_path: Path) -> None:
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(return_value=row)

    dataset_path = _write_dataset(tmp_path, [
        {"question": "doc1", "ground_truth": "gt", "scenario": "doc_only"},
        {"question": "abs1", "ground_truth": "gt", "scenario": "abstain"},
        {"question": "doc2", "ground_truth": "gt", "scenario": "doc_only"},
    ])

    called_questions: list[str] = []

    async def fake_answer_query(*args: Any, **kwargs: Any) -> Any:
        called_questions.append(kwargs["user_message"])
        return _answer_view("a", ["c"])

    fake_evaluator = MagicMock()
    fake_evaluator.judge_model = "llama3.1"
    fake_evaluator.evaluate = MagicMock(return_value=[{}, {}])

    report = await run_ragas_evaluation(
        MagicMock(), ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        answer_query=fake_answer_query,
        evaluator=fake_evaluator,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        llm_dispatcher=MagicMock(),
        settings=MagicMock(),
        chatbot_id=row.id,
        dataset_path=dataset_path,
        scenario_filter="doc_only",
    )
    assert called_questions == ["doc1", "doc2"]
    assert report.scenario_filter == "doc_only"


@pytest.mark.asyncio
async def test_answer_query_failure_marks_case_with_error(
    tmp_path: Path,
) -> None:
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(return_value=row)
    dataset_path = _write_dataset(tmp_path, [
        {"question": "Q1?", "ground_truth": "gt", "scenario": "doc_only"},
        {"question": "Q2?", "ground_truth": "gt", "scenario": "doc_only"},
    ])

    answers = [_answer_view("good", ["c"]), RuntimeError("LLM exploded")]
    idx = 0

    async def fake_answer_query(*args: Any, **kwargs: Any) -> Any:
        nonlocal idx
        result = answers[idx]
        idx += 1
        if isinstance(result, Exception):
            raise result
        return result

    fake_evaluator = MagicMock()
    fake_evaluator.judge_model = "llama3.1"
    fake_evaluator.evaluate = MagicMock(
        return_value=[
            {"faithfulness": 0.7, "answer_relevancy": 0.8,
             "context_precision": 0.7, "context_recall": 0.6},
            {},  # the errored case
        ]
    )

    report = await run_ragas_evaluation(
        MagicMock(), ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        answer_query=fake_answer_query,
        evaluator=fake_evaluator,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        llm_dispatcher=MagicMock(),
        settings=MagicMock(),
        chatbot_id=row.id,
        dataset_path=dataset_path,
        scenario_filter=None,
    )
    assert report.summary.num_scored == 1
    assert report.summary.num_errors == 1
    assert "LLM exploded" in report.cases[1].error


@pytest.mark.asyncio
async def test_raises_when_chatbot_not_found(tmp_path: Path) -> None:
    ctx = _ctx()
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(side_effect=NotFoundError("nope"))

    dataset_path = _write_dataset(tmp_path, [
        {"question": "Q?", "ground_truth": "gt", "scenario": "doc_only"},
    ])

    async def fake_unused(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("should not be called")

    fake_eval = MagicMock()
    fake_eval.judge_model = "llama3.1"

    with pytest.raises(ChatbotNotFoundError):
        await run_ragas_evaluation(
            MagicMock(), ctx,
            chatbot_repo_factory=lambda s, c: chatbot_repo,
            answer_query=fake_unused,
            evaluator=fake_eval,
            qdrant=MagicMock(),
            embedder_dispatcher=MagicMock(),
            llm_dispatcher=MagicMock(),
            settings=MagicMock(),
            chatbot_id=uuid4(),
            dataset_path=dataset_path,
            scenario_filter=None,
        )


@pytest.mark.asyncio
async def test_raises_when_dataset_is_empty_after_filter(
    tmp_path: Path,
) -> None:
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(return_value=row)

    dataset_path = _write_dataset(tmp_path, [
        {"question": "Q?", "ground_truth": "gt", "scenario": "abstain"},
    ])

    async def fake_unused(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("should not be called")

    fake_eval = MagicMock()
    fake_eval.judge_model = "llama3.1"

    with pytest.raises(EvaluationError, match="empty"):
        await run_ragas_evaluation(
            MagicMock(), ctx,
            chatbot_repo_factory=lambda s, c: chatbot_repo,
            answer_query=fake_unused,
            evaluator=fake_eval,
            qdrant=MagicMock(),
            embedder_dispatcher=MagicMock(),
            llm_dispatcher=MagicMock(),
            settings=MagicMock(),
            chatbot_id=row.id,
            dataset_path=dataset_path,
            scenario_filter="doc_only",  # filters everything out
        )
```

- [ ] **Step 4.6: Run, confirm collection failure**

```bash
pytest tests/unit/test_run_ragas_evaluation.py -v
```

Expected: collection error.

- [ ] **Step 4.7: Create `backend/src/tfm_rag/application/evaluation/run_ragas_evaluation.py`**

```python
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.chat.answer_query import (
    AnswerView,
    answer_query as _real_answer_query,
)
from tfm_rag.application.evaluation.dataset_loader import (
    load_evaluation_dataset,
)
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.evaluation import EvaluationError
from tfm_rag.domain.value_objects.evaluation_report import (
    EvaluationReport,
    EvaluationSummary,
)
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.evaluation.ragas_evaluator import RagasEvaluator
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

_log = logging.getLogger(__name__)

ChatbotRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatbotRepository
]
AnswerQuery = Callable[..., Awaitable[AnswerView]]


def _default_chatbot_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatbotRepository:
    return ChatbotRepository(session, ctx)


async def run_ragas_evaluation(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    chatbot_repo_factory: ChatbotRepoFactory = _default_chatbot_repo,
    answer_query: AnswerQuery = _real_answer_query,
    evaluator: RagasEvaluator,
    qdrant: QdrantStore,
    embedder_dispatcher: EmbedderDispatcher,
    llm_dispatcher: LLMDispatcher,
    settings: Settings,
    chatbot_id: UUID,
    dataset_path: Path,
    scenario_filter: str | None,
    progress: Callable[[int, int, str], None] | None = None,
) -> EvaluationReport:
    """Run the RAGAS evaluation pipeline.

    1. Validate the chatbot exists in the tenant.
    2. Load the dataset (with optional scenario filter).
    3. For each case: run ``answer_query(persist=False)`` to produce a
       prediction + retrieved_contexts. Errors are caught per-case and
       stored on ``case.error``.
    4. Hand the batch to ``evaluator.evaluate(cases)`` to compute RAGAS
       metrics. Errored cases / no-context cases are skipped by the
       evaluator (it returns ``{}`` for those positions).
    5. Build the EvaluationReport with a Summary aggregating the scores.

    ``progress`` is an optional callback (case_idx, total, status) — the
    CLI uses it to print one line per case to stdout.
    """
    # --- Step 1: validate chatbot ---
    chatbot_repo = chatbot_repo_factory(session, ctx)
    try:
        chatbot_row = await chatbot_repo.get(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc

    # --- Step 2: load dataset ---
    cases = load_evaluation_dataset(dataset_path, scenario_filter=scenario_filter)
    if not cases:
        raise EvaluationError(
            f"Dataset is empty after applying scenario_filter="
            f"{scenario_filter!r}"
        )

    started_at = datetime.now(timezone.utc)
    total = len(cases)

    # --- Step 3: run each case ---
    for idx, case in enumerate(cases):
        if progress is not None:
            progress(idx + 1, total, f"asking: {case.question[:60]}")
        try:
            view = await answer_query(
                session, ctx,
                llm_dispatcher=llm_dispatcher,
                qdrant=qdrant,
                embedder_dispatcher=embedder_dispatcher,
                settings=settings,
                chatbot_id=chatbot_id,
                session_id=None,
                user_message=case.question,
                persist=False,
            )
            case.predicted_answer = view.content
            case.retrieved_contexts = list(view.retrieved_contexts)
            case.citations = [c.to_dict() for c in view.citations]
            case.iterations = [it.to_dict() for it in view.iterations]
        except Exception as exc:  # noqa: BLE001 — record then continue
            case.error = f"{type(exc).__name__}: {exc}"
            _log.warning(
                "run_ragas_evaluation: case %d/%d failed: %s",
                idx + 1, total, exc,
            )

    # --- Step 4: RAGAS metrics ---
    if progress is not None:
        progress(total, total, "scoring with RAGAS...")
    per_case_scores = evaluator.evaluate(cases)
    for case, scores in zip(cases, per_case_scores, strict=True):
        if scores and case.error is None:
            case.scores = scores

    # --- Step 5: build report ---
    finished_at = datetime.now(timezone.utc)
    summary = EvaluationSummary.from_cases(cases)
    report = EvaluationReport(
        chatbot_id=chatbot_id,
        chatbot_name=chatbot_row.name,
        dataset_path=str(dataset_path),
        scenario_filter=scenario_filter,
        run_started_at=started_at,
        run_finished_at=finished_at,
        ragas_judge_model=evaluator.judge_model,
        cases=cases,
        summary=summary,
    )
    return report
```

- [ ] **Step 4.8: Run use case tests, expect 5 PASSED**

```bash
pytest tests/unit/test_run_ragas_evaluation.py -v
```

Expected: **5 PASSED**.

- [ ] **Step 4.9: Run all Task 4 tests, expect 9 PASSED**

```bash
pytest tests/unit/test_report_writer.py tests/unit/test_run_ragas_evaluation.py -v
```

Expected: **9 PASSED** (4 + 5).

- [ ] **Step 4.10: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/application/evaluation/report_writer.py backend/src/tfm_rag/application/evaluation/run_ragas_evaluation.py backend/tests/unit/test_report_writer.py backend/tests/unit/test_run_ragas_evaluation.py
git commit -m "feat(eval): run_ragas_evaluation orchestrator + report writer (JSON + Markdown)"
```

---

## Task 5 — CLI entry point

**Files:**
- Create: `backend/src/tfm_rag/cli/eval_ragas.py`

(Note: this task is small — just the argparse + entry wiring. We don't add unit tests for the CLI itself because `argparse` boilerplate is rarely the bug source; the integration test in Task 6 will exercise the CLI end-to-end.)

- [ ] **Step 5.1: Create `backend/src/tfm_rag/cli/eval_ragas.py`**

```python
"""CLI entry point: ``python -m tfm_rag.cli.eval_ragas`` (or ``eval-ragas``
via the script entry in pyproject.toml).

Reads settings from .env (the same way the API does), builds a one-off
DB session, runs the eval pipeline, writes ``report.json`` + ``report.md``
to ``--output-dir`` (default: ``eval_runs/<UTC-timestamp>/``).
"""
import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from tfm_rag.application.evaluation.report_writer import write_report
from tfm_rag.application.evaluation.run_ragas_evaluation import (
    run_ragas_evaluation,
)
from tfm_rag.domain.catalog.eval_scenarios import KNOWN_SCENARIOS
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.evaluation import (
    EvaluationDatasetError,
    EvaluationError,
)
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.evaluation.ragas_evaluator import RagasEvaluator
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import get_settings
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

_log = logging.getLogger(__name__)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="eval-ragas",
        description=(
            "Run a RAGAS evaluation against a chatbot. Writes report.json "
            "+ report.md to --output-dir."
        ),
    )
    p.add_argument(
        "--chatbot-id", required=True, type=UUID,
        help="UUID of the chatbot to evaluate.",
    )
    p.add_argument(
        "--tenant-id", required=True, type=UUID,
        help=(
            "UUID of the tenant the chatbot belongs to. Required because "
            "the CLI runs without an auth middleware."
        ),
    )
    p.add_argument(
        "--dataset", required=True, type=Path,
        help="Path to the JSONL evaluation dataset.",
    )
    p.add_argument(
        "--scenario", default=None,
        choices=sorted(KNOWN_SCENARIOS),
        help="Filter dataset to entries with this scenario.",
    )
    p.add_argument(
        "--judge-model", default=None,
        help=(
            "Override the LLM used by RAGAS as judge. Defaults to the "
            "chatbot's own model_id (recommended for self-consistent runs)."
        ),
    )
    p.add_argument(
        "--embedding-model", default="bge-m3",
        help="Embedding model RAGAS uses for context_precision/recall.",
    )
    p.add_argument(
        "--output-dir", default=None, type=Path,
        help=(
            "Directory for report.json + report.md. Defaults to "
            "eval_runs/<UTC-timestamp>/."
        ),
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print one line per case as it runs.",
    )
    return p


def _print_progress(idx: int, total: int, status: str) -> None:
    print(f"[{idx}/{total}] {status}", flush=True)


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    output_dir = args.output_dir or Path(
        f"eval_runs/{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )

    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    qdrant = QdrantStore(settings.qdrant_url, settings.qdrant_api_key)
    try:
        async with factory() as db_session:
            ctx = RequestContext(tenant_id=args.tenant_id, user_id=None)

            # Resolve judge model: use chatbot's own model_id if no override.
            judge_model = args.judge_model
            if judge_model is None:
                # Peek the chatbot to learn its model. Done lazily here
                # rather than threading another arg into the use case.
                from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
                    ChatbotRepository,
                )
                repo = ChatbotRepository(db_session, ctx)
                try:
                    row = await repo.get(args.chatbot_id)
                except Exception:
                    print(
                        f"error: chatbot {args.chatbot_id} not found in tenant "
                        f"{args.tenant_id}",
                        file=sys.stderr,
                    )
                    return 2
                judge_model = row.llm_selection["model_id"]

            evaluator = RagasEvaluator(
                base_url=settings.ollama_base_url,
                judge_model=judge_model,
                embedding_model=args.embedding_model,
            )

            report = await run_ragas_evaluation(
                db_session, ctx,
                evaluator=evaluator,
                qdrant=qdrant,
                embedder_dispatcher=EmbedderDispatcher.default(),
                llm_dispatcher=LLMDispatcher.default(),
                settings=settings,
                chatbot_id=args.chatbot_id,
                dataset_path=args.dataset,
                scenario_filter=args.scenario,
                progress=_print_progress if args.verbose else None,
            )

        paths = write_report(report, output_dir=output_dir)
        print(f"report.json: {paths.json_path}")
        print(f"report.md:   {paths.markdown_path}")
        print(
            f"Summary: {report.summary.num_scored}/{report.summary.num_cases} "
            f"scored, {report.summary.num_errors} errors."
        )
        for metric, value in sorted(report.summary.metrics.items()):
            print(f"  {metric:>20s}: {value:.3f}")
        return 0
    finally:
        await qdrant.close()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = _build_arg_parser()
    args = parser.parse_args()
    try:
        exit_code = asyncio.run(_run(args))
    except EvaluationDatasetError as exc:
        print(f"dataset error: {exc}", file=sys.stderr)
        sys.exit(2)
    except ChatbotNotFoundError as exc:
        print(f"chatbot not found: {exc}", file=sys.stderr)
        sys.exit(2)
    except EvaluationError as exc:
        print(f"evaluation error: {exc}", file=sys.stderr)
        sys.exit(3)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5.2: Verify the CLI imports cleanly and shows help**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
python -m tfm_rag.cli.eval_ragas --help
```

Expected: argparse help output listing all flags.

Also verify the script entry works:

```bash
eval-ragas --help
```

Expected: same argparse help (via the entry in `pyproject.toml [project.scripts]`).

- [ ] **Step 5.3: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/cli/eval_ragas.py
git commit -m "feat(cli): eval-ragas CLI (argparse, bootstraps DB, writes reports)"
```

---

## Task 6 — Integration test: end-to-end CLI vs live Ollama

This test is **slow** (~3-6 minutes). It ingests a small doc, creates a chatbot, runs the CLI against a tiny inline dataset, asserts both report files exist with sensible structure.

**Files:**
- Create: `backend/tests/integration/test_eval_ragas_cli_flow.py`

- [ ] **Step 6.1: Create the integration test**

```python
"""End-to-end test for the eval-ragas CLI.

Requires the live Docker stack (postgres + qdrant + ollama with llama3.1
+ bge-m3). The CLI is invoked via subprocess so the test exercises the
real entry point and process boundary.

NOTE: this is the slowest test in the repo (~3-6 minutes). It's marked
`integration` and only runs when explicitly selected.
"""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import tfm_rag.infrastructure.api.dependencies as _deps
from tfm_rag.infrastructure.api.app import app
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
async def _clean_state(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE chat_messages, chat_sessions, "
            "chatbot_knowledge_base, chatbots, ingestion_jobs, "
            "sources, knowledge_bases, provider_credentials, users, tenants "
            "RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()
    _deps._session_factory = None


async def _register(client: AsyncClient, email: str) -> tuple[str, str]:
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return body["token"], body["tenant_id"]


async def _ingest_doc(
    client: AsyncClient, token: str, kb_id: str, body: bytes
) -> None:
    h = {"Authorization": f"Bearer {token}"}
    upload = await client.post(
        f"/api/knowledge-bases/{kb_id}/sources/documents",
        headers=h,
        files={"file": ("manual.txt", body, "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    job_id = upload.json()["job_id"]
    for _ in range(120):
        await asyncio.sleep(1)
        r = await client.get(f"/api/ingestion-jobs/{job_id}", headers=h)
        if r.json()["status"] in {"done", "failed"}:
            assert r.json()["status"] == "done", r.json()
            return
    raise AssertionError("ingestion did not finish in 2 min")


async def test_eval_ragas_cli_produces_reports(
    _clean_state: None, tmp_path: Path,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=180.0) as client:
        token, tenant_id_str = await _register(client, "eval-cli@example.com")
        h = {"Authorization": f"Bearer {token}"}

        creds = (await client.get("/api/credentials", headers=h)).json()
        cred_id = next(c for c in creds if c["provider_id"] == "ollama")["id"]

        # 1) Create a KB with the Ollama bge-m3 embedder
        r = await client.post(
            "/api/knowledge-bases", headers=h,
            json={
                "name": "EvalKB",
                "embedding_selection": {
                    "provider_id": "ollama",
                    "credential_id": cred_id,
                    "model_id": "bge-m3",
                    "dim": 1024,
                },
                "chunking_config": {
                    "strategy": "fixed",
                    "chunk_size": 300,
                    "chunk_overlap": 50,
                },
            },
        )
        kb_id = r.json()["id"]

        # 2) Ingest a small fact-dense doc
        body = (
            b"The Spanish Civil War lasted from July 17, 1936 until April 1, 1939. "
            b"The Nationalists were led by General Francisco Franco. "
            b"Franco died in 1975, ending nearly four decades of dictatorship."
        )
        await _ingest_doc(client, token, kb_id, body)

        # 3) Create a chatbot
        r = await client.post(
            "/api/chatbots", headers=h,
            json={
                "name": "EvalBot",
                "system_prompt": (
                    "Answer concisely using search_docs to ground your answer."
                ),
                "llm_selection": {
                    "provider_id": "ollama", "credential_id": cred_id,
                    "model_id": "llama3.1",
                },
                "kb_ids": [kb_id],
                "pipeline_config": {
                    "top_k": 3,
                    "max_retrieval_iterations": 3,
                },
                "widget_config": {},
            },
        )
        chatbot_id = r.json()["id"]

        # 4) Write a tiny dataset
        dataset = tmp_path / "ds.jsonl"
        dataset.write_text(
            json.dumps({
                "question": "When did the Spanish Civil War end?",
                "ground_truth": "April 1, 1939.",
                "scenario": "doc_only",
                "metadata": {"difficulty": "easy"},
            }) + "\n" +
            json.dumps({
                "question": "Who led the Nationalists?",
                "ground_truth": "Francisco Franco.",
                "scenario": "doc_only",
                "metadata": {"difficulty": "easy"},
            }) + "\n",
            encoding="utf-8",
        )
        output_dir = tmp_path / "report-dir"

        # 5) Invoke the CLI via subprocess so we exercise the real entry point
        env = {
            **os.environ,
            "POSTGRES_URL": "postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag",
            "QDRANT_URL": "http://localhost:6333",
            "OLLAMA_BASE_URL": "http://localhost:11434",
            "JWT_SECRET": "1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA",
            "FERNET_KEY": "8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=",
            "STORAGE_LOCAL_PATH": "/tmp/tfm_rag_storage",
        }
        cmd = [
            sys.executable, "-m", "tfm_rag.cli.eval_ragas",
            "--chatbot-id", chatbot_id,
            "--tenant-id", tenant_id_str,
            "--dataset", str(dataset),
            "--scenario", "doc_only",
            "--output-dir", str(output_dir),
            "--verbose",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=600.0
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise AssertionError("eval-ragas CLI timed out after 10 min")
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")

        # 6) Verify CLI exited 0 + reports landed
        assert proc.returncode == 0, (
            f"CLI exited {proc.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        )
        report_json = output_dir / "report.json"
        report_md = output_dir / "report.md"
        assert report_json.exists()
        assert report_md.exists()

        data = json.loads(report_json.read_text(encoding="utf-8"))
        assert data["chatbot_name"] == "EvalBot"
        assert data["scenario_filter"] == "doc_only"
        assert data["summary"]["num_cases"] == 2
        # We allow some cases to score 0 (LLM judge variance), but the
        # pipeline must have completed without errors AND at least one
        # case must have produced an answer (predicted_answer non-null).
        assert data["summary"]["num_errors"] == 0
        answered = [
            c for c in data["cases"]
            if c.get("predicted_answer") and c["predicted_answer"].strip()
        ]
        assert len(answered) >= 1, (
            "No cases produced a non-empty answer; check the CLI stdout:\n"
            + stdout
        )

        # Markdown contains the summary table
        md = report_md.read_text(encoding="utf-8")
        assert "# Evaluation report — EvalBot" in md
        assert "| Metric | Score |" in md
```

- [ ] **Step 6.2: Reset DB schema and run the integration test**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
docker exec tfm-rag-postgres-1 psql -U tfm -d tfm_rag \
  -c "DROP TABLE IF EXISTS chat_messages, chat_sessions, chatbot_knowledge_base, chatbots, ingestion_jobs, sources, knowledge_bases, provider_credentials, users, tenants, alembic_version CASCADE;"
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
alembic upgrade head
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration/test_eval_ragas_cli_flow.py -m integration -v --timeout=900
```

Expected: **1 PASSED** (slow — 3-6 minutes). The CLI runs the agent loop twice (one per question) AND then runs RAGAS scoring (which fires multiple LLM calls per metric per case).

**If the test fails:**
- `ragas` / `langchain-ollama` import error → run `pip install -e '.[eval,dev]'` first.
- `model 'llama3.1' not found` → check `ollama list` on the HOST (not the container — see handover §8 about the dual-Ollama gotcha).
- Test times out at 10 minutes → RAGAS may be retrying internally. Re-run; if it keeps timing out, the RAGAS judge model may be too slow on llama3.1. Try `--judge-model llama3.1:instruct` or escalate.

- [ ] **Step 6.3: Run the full integration suite to verify no regression**

```bash
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration -m integration -v --timeout=900
```

Expected: previous 28 + 1 new = **29 PASSED**.

- [ ] **Step 6.4: Commit + tag**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/tests/integration/test_eval_ragas_cli_flow.py
git commit -m "test(eval): end-to-end eval-ragas CLI vs live Ollama (slow, ~5min)"
git tag cap-17-eval-ragas
```

---

## Controller cleanup (post-subagent — NOT a task)

After all 6 tasks land, the controller runs the global lint pass:

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
ruff check . --fix
mypy src/
pytest tests/ -m "not integration"
```

If autofixes / type fixes are applied, commit them as `chore(plan-17): ruff autofix` and **move the `cap-17-eval-ragas` tag forward** to that cleanup commit (project convention — see handover §8).

```bash
git tag -f cap-17-eval-ragas <cleanup-commit-sha>
```

---

## What's next after plan #17

After plan #17 lands, **4 plans remain (4/17)**: #9 (KB-DB-SOURCES, M4), #11 (CHATBOT-WIDGET-CONFIG), #13 (CHAT-SQL-EXECUTION, completes M4), #16 (WIDGET-RUNTIME, M5). All orthogonal to the M3+M6 demo already operational.

Small follow-ups that pair well with plan #17:
- **Matrix comparison subcommand** (`eval-ragas compare --runs ...`) for the spec's "reranker on/off, agentic_mode, ..." variables table. Just iterates the existing CLI.
- **Public dataset adapters** (RAG-12000, MS MARCO, SQuAD) — each one is a small `dataset_loader` variant.
- **CI-friendly eval mode**: a small bundled dataset + thresholds in `.toml` to fail the build if metrics regress. Useful for the TFM defense ("the system is empirically tested").
