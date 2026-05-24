# CAP-CHAT-AGENT-LOOP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the final piece of M3 — the `AnswerQuery` agent loop and `POST /api/chatbots/{chatbot_id}/chat`. A user asks a question, the LLM (Ollama llama3.1) decides between `search_docs` / `final_answer` / `abstain` over up to N iterations, the chatbot returns a cited answer. Session + messages persist via the plan #14 helpers.

**Architecture:**
- **New port `LLMProvider`** with `generate(messages, tools, ...) → LLMToolCall | LLMTextResponse`. Concrete adapter `OllamaLLMAdapter` calls Ollama's `/api/chat` with tool calling (supported on llama3.1 since Ollama 0.4). An `LLMDispatcher` analogous to `EmbedderDispatcher` routes by `provider_id`. Plan #15 wires only `ollama`; `openai` / `openai_compat` adapters land in later plans.
- **Tool catalog** in `domain/catalog/agent_tools.py` — single source of truth for tool names (`TOOL_SEARCH_DOCS`, `TOOL_FINAL_ANSWER`, `TOOL_ABSTAIN`, `TOOL_QUERY_DATABASE`) AND for their JSON-Schema function definitions. The agent loop and the Ollama adapter both read from here. `query_database` is declared but NOT included in the schemas presented to the LLM in M3 (it lands in plan #13 CHAT-SQL-EXECUTION).
- **Typed VOs** `Citation` (referenced by `ChatMessage.citations`) and `RetrievalIteration` (referenced by `ChatMessage.metadata.iterations[]`). Plan #14 stored these as opaque dicts; plan #15 introduces the canonical shapes. The use case writes VOs → `.to_dict()` into JSONB.
- **`answer_query` use case** is the agent loop. Pseudocode:
  ```
  load chatbot (must exist in tenant)
  if session_id is None: create_session(chatbot_id, origin=playground)
  append_message(session, role=user, content=user_message)
  messages = [system_prompt + tool meta-prompt, user_message]
  iterations = []
  seen_chunks: dict[point_id → RetrievedChunk] = {}
  for i in 0..max_retrieval_iterations:
      response = llm.generate(messages, tools=[search_docs, final_answer, abstain])
      if response is LLMTextResponse: treat as final answer
      elif response is LLMToolCall(final_answer): break with answer
      elif response is LLMToolCall(abstain): break with abstain
      elif response is LLMToolCall(search_docs): retrieve_docs → seen_chunks.update → append tool result to messages, loop
      else: raise
  if no terminal decision after N iterations: synthesise abstain
  citations = [Citation.from_chunk(c) for c in seen_chunks.values()]
  append_message(session, role=assistant, content=answer, citations, metadata={iterations: [...]})
  touch_session(session)
  return AnswerView(session_id, message_id, content, citations, iterations)
  ```
- **API endpoint** `POST /api/chatbots/{chatbot_id}/chat` accepts `{session_id?, message}` and returns JSON (no SSE in plan #15 — the demo works fine without streaming; SSE is a small follow-up).
- **No new DB tables.** All persistence reuses `chat_sessions` + `chat_messages` from plan #14. Tag at the end: `cap-15-chat-agent-loop`.

**Tech Stack:** `httpx` (already a dep) for the Ollama adapter. No new packages.

**Depends on:**
- Plan #10 (chatbots — for `ChatbotRepository.get` + `list_kb_ids` + `PipelineConfig`).
- Plan #12 (`retrieve_docs` — used as the `search_docs` tool implementation).
- Plan #14 (`chat_sessions` + `chat_messages` + `create_session` / `append_message` / `touch_session` helpers).

**Out of scope (deferred):**
- **SSE / streaming.** Plan #15 returns one JSON response. Follow-up plan can add `text/event-stream` to the same endpoint.
- **`query_database` tool.** Declared as a constant in the agent_tools catalog so plan #13 can register the schema without circular deps, but NOT presented to the LLM in M3.
- **`openai` / `openai_compat` LLM adapters.** Only `OllamaLLMAdapter` ships. The dispatcher pattern keeps the seam ready.
- **Router LLM (cheap-model fallback for tool selection).** `PipelineConfig.router_llm_selection` is read but unused in M3 — the main `chatbot.llm_selection` drives the loop. A follow-up can switch tool-selection turns to the router model.
- **Token-level cost/latency tracking.** `RetrievalIteration.latency_ms` is captured per iteration, but no usage metrics endpoint.
- **In-text citation markers** (`[1]`, `[2]`). We attach all chunks seen during the loop as citations on the assistant message; we don't post-process the answer to inline markers. UI can render the citation list separately.
- **Reranker integration in the chat loop.** `retrieve_docs` already accepts a `reranker` param. Plan #15 calls `retrieve_docs(..., reranker=None)` — wiring the reranker into the chat loop is a tiny follow-up once a `BGECrossEncoderReranker` adapter exists.

**On centralised string constants (per project policy):** All new domain strings introduced by plan #15 (tool names, role names already in `Literal[...]`, etc.) live in `domain/catalog/agent_tools.py`. Existing literals elsewhere in the repo (`"ollama"`, `"playground"`, ...) are NOT refactored in this plan.

---

## File structure

```
backend/src/tfm_rag/
├── domain/
│   ├── catalog/
│   │   └── agent_tools.py                      # NEW: tool name constants + JSON schemas
│   ├── value_objects/
│   │   ├── citation.py                         # NEW: Citation VO
│   │   ├── retrieval_iteration.py              # NEW: RetrievalIteration + LLM response VOs
│   ├── ports/
│   │   └── llm.py                              # NEW: LLMProvider Protocol
│   └── errors/
│       └── chat.py                             # MODIFY: +LLMError, +LLMTimeoutError, +MaxIterationsExceededError
│
├── infrastructure/
│   ├── llm_providers/                          # NEW pkg
│   │   ├── __init__.py
│   │   ├── ollama.py                           # NEW: OllamaLLMAdapter
│   │   └── dispatcher.py                       # NEW: LLMDispatcher
│   └── api/
│       └── routers/
│           └── chatbots.py                     # MODIFY: +POST /{chatbot_id}/chat
│
└── application/
    └── chat/
        └── answer_query.py                     # NEW: the agent loop use case

backend/tests/unit/
├── test_citation_vo.py                         # NEW
├── test_retrieval_iteration_vo.py              # NEW
├── test_agent_tools_catalog.py                 # NEW
├── test_ollama_llm_adapter.py                  # NEW
├── test_llm_dispatcher.py                      # NEW
└── test_answer_query.py                        # NEW (the agent loop, with fakes)

backend/tests/integration/
└── test_chat_agent_loop_flow.py                # NEW (end-to-end vs live Ollama)
```

---

## Task 1 — Domain: tool catalog + VOs + LLM port + errors

**Files:**
- Create: `backend/src/tfm_rag/domain/catalog/agent_tools.py`
- Create: `backend/src/tfm_rag/domain/value_objects/citation.py`
- Create: `backend/src/tfm_rag/domain/value_objects/retrieval_iteration.py`
- Create: `backend/src/tfm_rag/domain/ports/llm.py`
- Modify: `backend/src/tfm_rag/domain/errors/chat.py` (3 new errors)
- Create: `backend/tests/unit/test_citation_vo.py`
- Create: `backend/tests/unit/test_retrieval_iteration_vo.py`
- Create: `backend/tests/unit/test_agent_tools_catalog.py`

- [ ] **Step 1.1: Write failing tests for `Citation`**

Create `backend/tests/unit/test_citation_vo.py`:

```python
from uuid import uuid4

import pytest

from tfm_rag.domain.value_objects.citation import Citation
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk


def _chunk(content: str = "x") -> RetrievedChunk:
    return RetrievedChunk(
        point_id="pid-1",
        content=content,
        source_id=uuid4(),
        source_filename="manual.pdf",
        chunk_index=2,
        score=0.87,
        metadata={"chunk_start": 100, "chunk_end": 200},
    )


def test_citation_from_chunk_promotes_fields() -> None:
    chunk = _chunk("alpha")
    cit = Citation.from_chunk(chunk)
    assert cit.chunk_id == "pid-1"
    assert cit.source_id == chunk.source_id
    assert cit.source_name == "manual.pdf"
    assert cit.score == 0.87
    # `location` derives from chunk_index by default
    assert cit.location == "chunk#2"


def test_citation_round_trip_dict() -> None:
    cit = Citation.from_chunk(_chunk())
    data = cit.to_dict()
    assert set(data) == {
        "chunk_id", "source_id", "source_name", "location", "score"
    }
    assert data["source_id"] == str(cit.source_id)
    assert data["score"] == cit.score
    # from_dict reconstructs equivalent
    cit2 = Citation.from_dict(data)
    assert cit2 == cit


def test_citation_rejects_score_out_of_range() -> None:
    from tfm_rag.domain.errors.common import ValidationError
    with pytest.raises(ValidationError):
        Citation(
            chunk_id="x", source_id=uuid4(), source_name="x",
            location="x", score=1.5,
        )
```

- [ ] **Step 1.2: Run, confirm collection failure**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pytest tests/unit/test_citation_vo.py -v
```

Expected: collection error — `citation` module does not exist.

- [ ] **Step 1.3: Create `backend/src/tfm_rag/domain/value_objects/citation.py`**

```python
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk


@dataclass(frozen=True, slots=True)
class Citation:
    """A reference attached to an assistant message. Pointer back to the
    chunk that grounded a piece of the answer.

    `location` is a human-readable hint about where in the source the chunk
    lives (e.g. `"chunk#7"`, `"page 12"`). For MVP we derive it from
    `chunk_index`; loaders can override later by passing a richer
    `metadata.location` on the source RetrievedChunk.

    Persisted as a JSONB dict inside `chat_messages.citations[]`. The
    canonical shape is the one returned by `to_dict()`.
    """

    chunk_id: str
    source_id: UUID
    source_name: str
    location: str
    score: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.score <= 1.0):
            raise ValidationError(
                f"Citation.score must be in [0, 1], got {self.score}"
            )

    @classmethod
    def from_chunk(cls, chunk: RetrievedChunk) -> "Citation":
        location = str(chunk.metadata.get("location") or f"chunk#{chunk.chunk_index}")
        return cls(
            chunk_id=chunk.point_id,
            source_id=chunk.source_id,
            source_name=chunk.source_filename,
            location=location,
            score=float(chunk.score),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source_id": str(self.source_id),
            "source_name": self.source_name,
            "location": self.location,
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Citation":
        return cls(
            chunk_id=str(data["chunk_id"]),
            source_id=UUID(str(data["source_id"])),
            source_name=str(data["source_name"]),
            location=str(data["location"]),
            score=float(data["score"]),
        )
```

- [ ] **Step 1.4: Run the Citation tests, expect 3 PASSED**

```bash
pytest tests/unit/test_citation_vo.py -v
```

Expected: **3 PASSED**.

- [ ] **Step 1.5: Write failing tests for `RetrievalIteration` + LLM response VOs**

Create `backend/tests/unit/test_retrieval_iteration_vo.py`:

```python
import pytest

from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMTextResponse,
    LLMToolCall,
    RetrievalIteration,
)


def test_retrieval_iteration_round_trip() -> None:
    it = RetrievalIteration(
        index=0,
        tool="search_docs",
        query="what is X",
        num_chunks=3,
        latency_ms=482.0,
    )
    data = it.to_dict()
    assert data == {
        "index": 0,
        "tool": "search_docs",
        "query": "what is X",
        "num_chunks": 3,
        "latency_ms": 482.0,
    }
    assert RetrievalIteration.from_dict(data) == it


def test_retrieval_iteration_accepts_terminal_tool_without_query() -> None:
    it = RetrievalIteration(
        index=1,
        tool="final_answer",
        query=None,
        num_chunks=None,
        latency_ms=120.5,
    )
    data = it.to_dict()
    # None values are kept (the JSONB column carries them — UI can hide).
    assert data["query"] is None
    assert data["num_chunks"] is None


def test_retrieval_iteration_negative_index_rejected() -> None:
    from tfm_rag.domain.errors.common import ValidationError

    with pytest.raises(ValidationError):
        RetrievalIteration(
            index=-1, tool="search_docs", query="x",
            num_chunks=0, latency_ms=0.0,
        )


def test_llm_tool_call_attribute_access() -> None:
    call = LLMToolCall(tool="search_docs", arguments={"query": "hi"})
    assert call.tool == "search_docs"
    assert call.arguments == {"query": "hi"}


def test_llm_text_response_attribute_access() -> None:
    resp = LLMTextResponse(text="hello world")
    assert resp.text == "hello world"
```

- [ ] **Step 1.6: Create `backend/src/tfm_rag/domain/value_objects/retrieval_iteration.py`**

```python
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from tfm_rag.domain.errors.common import ValidationError


@dataclass(frozen=True, slots=True)
class RetrievalIteration:
    """Telemetry for one turn of the agent loop. Persisted as a dict inside
    `chat_messages.metadata.iterations[]`.

    `tool` is one of the constants in `domain/catalog/agent_tools.py`. For
    `final_answer` and `abstain` turns, `query` and `num_chunks` will be
    None — the iteration captures the LLM decision, not a retrieval.
    """

    index: int
    tool: str
    query: str | None
    num_chunks: int | None
    latency_ms: float

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValidationError(
                f"RetrievalIteration.index must be >= 0, got {self.index}"
            )
        if self.latency_ms < 0:
            raise ValidationError(
                f"RetrievalIteration.latency_ms must be >= 0, got {self.latency_ms}"
            )
        if self.num_chunks is not None and self.num_chunks < 0:
            raise ValidationError(
                f"RetrievalIteration.num_chunks must be >= 0 if set, got {self.num_chunks}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "tool": self.tool,
            "query": self.query,
            "num_chunks": self.num_chunks,
            "latency_ms": self.latency_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetrievalIteration":
        return cls(
            index=int(data["index"]),
            tool=str(data["tool"]),
            query=(str(data["query"]) if data.get("query") is not None else None),
            num_chunks=(
                int(data["num_chunks"]) if data.get("num_chunks") is not None else None
            ),
            latency_ms=float(data["latency_ms"]),
        )


@dataclass(frozen=True, slots=True)
class LLMToolCall:
    """Returned by `LLMProvider.generate` when the model invoked a tool.

    `tool` is one of the constants in `domain/catalog/agent_tools.py`.
    `arguments` is the parsed JSON object passed to the tool.
    """

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict, hash=False)


@dataclass(frozen=True, slots=True)
class LLMTextResponse:
    """Returned by `LLMProvider.generate` when the model produced raw text
    without calling a tool. The agent loop treats this as an implicit
    final answer (defensive: if a model ignores the tool schema we still
    return SOMETHING to the user).
    """

    text: str


LLMResponse: TypeAlias = LLMToolCall | LLMTextResponse
```

- [ ] **Step 1.7: Run the RetrievalIteration tests, expect 5 PASSED**

```bash
pytest tests/unit/test_retrieval_iteration_vo.py -v
```

Expected: **5 PASSED**.

- [ ] **Step 1.8: Write failing tests for the agent_tools catalog**

Create `backend/tests/unit/test_agent_tools_catalog.py`:

```python
import pytest

from tfm_rag.domain.catalog import agent_tools


def test_tool_name_constants_are_distinct() -> None:
    names = {
        agent_tools.TOOL_SEARCH_DOCS,
        agent_tools.TOOL_FINAL_ANSWER,
        agent_tools.TOOL_ABSTAIN,
        agent_tools.TOOL_QUERY_DATABASE,
    }
    assert len(names) == 4


def test_tool_name_constants_have_expected_values() -> None:
    # The schema we present to the LLM uses these exact strings, so they
    # must NOT change without updating the LLM adapter's parsing.
    assert agent_tools.TOOL_SEARCH_DOCS == "search_docs"
    assert agent_tools.TOOL_FINAL_ANSWER == "final_answer"
    assert agent_tools.TOOL_ABSTAIN == "abstain"
    assert agent_tools.TOOL_QUERY_DATABASE == "query_database"


def test_build_tool_schemas_default_excludes_query_database() -> None:
    schemas = agent_tools.build_tool_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert agent_tools.TOOL_SEARCH_DOCS in names
    assert agent_tools.TOOL_FINAL_ANSWER in names
    assert agent_tools.TOOL_ABSTAIN in names
    assert agent_tools.TOOL_QUERY_DATABASE not in names


def test_build_tool_schemas_can_include_query_database() -> None:
    schemas = agent_tools.build_tool_schemas(include_query_database=True)
    names = {s["function"]["name"] for s in schemas}
    assert agent_tools.TOOL_QUERY_DATABASE in names


def test_each_tool_schema_has_required_keys() -> None:
    for schema in agent_tools.build_tool_schemas(include_query_database=True):
        assert schema["type"] == "function"
        fn = schema["function"]
        assert isinstance(fn["name"], str)
        assert isinstance(fn["description"], str)
        params = fn["parameters"]
        assert params["type"] == "object"
        assert "properties" in params


def test_search_docs_requires_query_argument() -> None:
    schemas = {s["function"]["name"]: s for s in agent_tools.build_tool_schemas()}
    s = schemas[agent_tools.TOOL_SEARCH_DOCS]
    assert "query" in s["function"]["parameters"]["properties"]
    assert "query" in s["function"]["parameters"]["required"]


def test_final_answer_requires_answer_argument() -> None:
    schemas = {s["function"]["name"]: s for s in agent_tools.build_tool_schemas()}
    s = schemas[agent_tools.TOOL_FINAL_ANSWER]
    assert "answer" in s["function"]["parameters"]["properties"]
    assert "answer" in s["function"]["parameters"]["required"]
```

- [ ] **Step 1.9: Create `backend/src/tfm_rag/domain/catalog/agent_tools.py`**

```python
"""Catalog of agent-loop tools.

Single source of truth for:
- The tool *names* that the LLM is told to choose from.
- The JSON-Schema function descriptors we pass to the LLM via the
  Chat Completions `tools` field (Ollama / OpenAI / OpenAI-compat all
  consume the same shape).
- A `build_tool_schemas()` helper that the agent loop and the LLM adapter
  both call so the source of truth lives here.

Add new tools by:
1. Declaring a `TOOL_*` constant.
2. Adding the JSON-Schema descriptor below.
3. Branching on the name in `application/chat/answer_query.py`.

Notes:
- `query_database` is declared but not included in the *default* schema
  list — plan #15 ships only the docs-retrieval loop. Plan #13
  (CHAT-SQL-EXECUTION) flips `include_query_database=True` and adds the
  branch in `answer_query`.
"""

from typing import Any

# Tool name constants. Identifiers used by the LLM in `tool_calls[].function.name`
# and branched on by the agent loop.
TOOL_SEARCH_DOCS = "search_docs"
TOOL_FINAL_ANSWER = "final_answer"
TOOL_ABSTAIN = "abstain"
TOOL_QUERY_DATABASE = "query_database"


_SEARCH_DOCS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_SEARCH_DOCS,
        "description": (
            "Search the knowledge base for documents relevant to a "
            "natural-language query. Returns excerpts (chunks) with "
            "their source filename. Call this before answering when the "
            "user's question can plausibly be answered from documents."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Natural-language search query. Should be the user's "
                        "question or a rephrased, focused version of it."
                    ),
                },
            },
            "required": ["query"],
        },
    },
}


_FINAL_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_FINAL_ANSWER,
        "description": (
            "Emit the final answer to the user. Call this when you have "
            "enough information to respond. The answer should be grounded "
            "in the documents you retrieved via search_docs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "description": "The natural-language answer for the user.",
                },
            },
            "required": ["answer"],
        },
    },
}


_ABSTAIN_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_ABSTAIN,
        "description": (
            "Decline to answer because the knowledge base does not contain "
            "the information needed. Use this instead of guessing when "
            "search_docs did not return relevant material."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": (
                        "Short explanation of what was missing or "
                        "ambiguous in the knowledge base."
                    ),
                },
            },
            "required": ["reason"],
        },
    },
}


_QUERY_DATABASE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_QUERY_DATABASE,
        "description": (
            "Execute a SQL SELECT against an attached read-only database "
            "source. (Plan #13 wires the executor; declared here so the "
            "tool catalog has a single source of truth.)"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "natural_language_request": {
                    "type": "string",
                    "description": (
                        "What you want to look up, in plain English. The "
                        "text2sql layer will translate to SQL."
                    ),
                },
            },
            "required": ["natural_language_request"],
        },
    },
}


def build_tool_schemas(
    *, include_query_database: bool = False
) -> list[dict[str, Any]]:
    """Return the list of tool schemas to present to the LLM.

    Plan #15 keeps `include_query_database=False`. Plan #13 will flip the
    flag when SQL execution lands.
    """
    schemas: list[dict[str, Any]] = [
        _SEARCH_DOCS_SCHEMA,
        _FINAL_ANSWER_SCHEMA,
        _ABSTAIN_SCHEMA,
    ]
    if include_query_database:
        schemas.append(_QUERY_DATABASE_SCHEMA)
    return schemas
```

- [ ] **Step 1.10: Run the catalog tests, expect 7 PASSED**

```bash
pytest tests/unit/test_agent_tools_catalog.py -v
```

Expected: **7 PASSED**.

- [ ] **Step 1.11: Create the LLM port `backend/src/tfm_rag/domain/ports/llm.py`**

```python
from typing import Protocol

from tfm_rag.domain.value_objects.retrieval_iteration import LLMResponse


class LLMProvider(Protocol):
    """Generates the next assistant turn given a conversation and a set of
    tools.

    `messages` follows the OpenAI Chat Completions shape:
        [
          {"role": "system", "content": "..."},
          {"role": "user", "content": "..."},
          {"role": "assistant", "tool_calls": [{"function": {...}}]},
          {"role": "tool", "tool_call_id": "...", "name": "...", "content": "..."},
          ...
        ]

    `tools` is the JSON-Schema list returned by
    `domain.catalog.agent_tools.build_tool_schemas()`. When `None`, the
    LLM is free to reply with plain text (returned as `LLMTextResponse`).

    `base_url` / `api_key` follow the same convention as
    `Embedder.embed` — SERVER_ENV providers (Ollama) get the value from
    Settings; TENANT_CREDENTIAL providers get a decrypted key.

    Adapters MUST translate provider-specific tool-call JSON into the
    domain VOs `LLMToolCall(tool, arguments)` or `LLMTextResponse(text)`.
    """

    async def generate(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model_id: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None,
        temperature: float,
        top_p: float,
        max_tokens: int,
    ) -> LLMResponse: ...
```

- [ ] **Step 1.12: Extend `backend/src/tfm_rag/domain/errors/chat.py`**

Open the existing file. After the existing `SessionNotFoundError` class, append:

```python


class LLMError(DomainError):
    """Raised when an LLM provider fails (HTTP error, malformed response,
    parsing error). The agent loop translates this into a 502 at the API
    layer.
    """


class LLMTimeoutError(LLMError):
    """Specialisation of LLMError for explicit timeouts (httpx.TimeoutException).
    Worth a dedicated type so observability dashboards can split them.
    """


class MaxIterationsExceededError(DomainError):
    """Raised when the agent loop hits `max_retrieval_iterations` without
    a terminal decision. The use case actually CATCHES this and synthesises
    an abstain — but it's defined here so tests can pin the behaviour.
    """
```

Then update the import at the top of the file. The current top-of-file
should now read:

```python
from tfm_rag.domain.errors.common import DomainError, NotFoundError
```

(Already true — no change needed; this comment is a sanity check.)

- [ ] **Step 1.13: Verify imports cleanly**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
python -c "from tfm_rag.domain.catalog.agent_tools import TOOL_SEARCH_DOCS, build_tool_schemas; print(len(build_tool_schemas()))"
python -c "from tfm_rag.domain.ports.llm import LLMProvider; print(LLMProvider.__doc__[:40])"
python -c "from tfm_rag.domain.value_objects.citation import Citation; from tfm_rag.domain.value_objects.retrieval_iteration import RetrievalIteration, LLMToolCall, LLMTextResponse; print('ok')"
python -c "from tfm_rag.domain.errors.chat import LLMError, LLMTimeoutError, MaxIterationsExceededError; print('errors ok')"
```

Expected:
```
3
Generates the next assistant
ok
errors ok
```

- [ ] **Step 1.14: Run all 15 new tests, expect 15 PASSED**

```bash
pytest tests/unit/test_citation_vo.py tests/unit/test_retrieval_iteration_vo.py tests/unit/test_agent_tools_catalog.py -v
```

Expected: **15 PASSED** (3 + 5 + 7).

- [ ] **Step 1.15: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/domain/catalog/agent_tools.py backend/src/tfm_rag/domain/value_objects/citation.py backend/src/tfm_rag/domain/value_objects/retrieval_iteration.py backend/src/tfm_rag/domain/ports/llm.py backend/src/tfm_rag/domain/errors/chat.py backend/tests/unit/test_citation_vo.py backend/tests/unit/test_retrieval_iteration_vo.py backend/tests/unit/test_agent_tools_catalog.py
git commit -m "feat(domain): Citation + RetrievalIteration VOs + LLMProvider port + agent_tools catalog"
```

---

## Task 2 — Infrastructure: Ollama LLM adapter + LLMDispatcher + unit tests

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/llm_providers/__init__.py`
- Create: `backend/src/tfm_rag/infrastructure/llm_providers/ollama.py`
- Create: `backend/src/tfm_rag/infrastructure/llm_providers/dispatcher.py`
- Create: `backend/tests/unit/test_ollama_llm_adapter.py`
- Create: `backend/tests/unit/test_llm_dispatcher.py`

- [ ] **Step 2.1: Write failing tests for `OllamaLLMAdapter`**

Create `backend/tests/unit/test_ollama_llm_adapter.py`:

```python
import json

import httpx
import pytest

from tfm_rag.domain.catalog.agent_tools import build_tool_schemas
from tfm_rag.domain.errors.chat import LLMError, LLMTimeoutError
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMTextResponse,
    LLMToolCall,
)
from tfm_rag.infrastructure.llm_providers.ollama import OllamaLLMAdapter


def _mock_transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_ollama_returns_tool_call_when_response_has_tool_calls() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "model": "llama3.1",
                "created_at": "2026-05-24T00:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "search_docs",
                                "arguments": {"query": "what is X"},
                            },
                        }
                    ],
                },
                "done": True,
            },
        )

    adapter = OllamaLLMAdapter(transport=_mock_transport(handler))
    resp = await adapter.generate(
        base_url="http://ollama:11434",
        api_key=None,
        model_id="llama3.1",
        messages=[
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "what is X"},
        ],
        tools=build_tool_schemas(),
        temperature=0.2,
        top_p=1.0,
        max_tokens=1024,
    )

    assert isinstance(resp, LLMToolCall)
    assert resp.tool == "search_docs"
    assert resp.arguments == {"query": "what is X"}

    # The request body matches Ollama's chat API shape
    body = captured["body"]
    assert body["model"] == "llama3.1"
    assert body["stream"] is False
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "system"
    assert len(body["tools"]) == 3  # search_docs + final_answer + abstain
    assert body["options"]["temperature"] == 0.2
    assert body["options"]["top_p"] == 1.0
    assert body["options"]["num_predict"] == 1024
    assert captured["url"].endswith("/api/chat")


@pytest.mark.asyncio
async def test_ollama_returns_text_response_when_no_tool_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "llama3.1",
                "message": {
                    "role": "assistant",
                    "content": "hello, I am a language model.",
                },
                "done": True,
            },
        )

    adapter = OllamaLLMAdapter(transport=_mock_transport(handler))
    resp = await adapter.generate(
        base_url="http://ollama:11434",
        api_key=None,
        model_id="llama3.1",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        temperature=0.2,
        top_p=1.0,
        max_tokens=1024,
    )

    assert isinstance(resp, LLMTextResponse)
    assert resp.text == "hello, I am a language model."


@pytest.mark.asyncio
async def test_ollama_parses_string_arguments_into_dict() -> None:
    """Some Ollama versions return tool arguments as a JSON-encoded string
    rather than a parsed object. The adapter MUST handle both shapes.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "llama3.1",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "final_answer",
                                "arguments": '{"answer": "X is a thing"}',
                            },
                        }
                    ],
                },
                "done": True,
            },
        )

    adapter = OllamaLLMAdapter(transport=_mock_transport(handler))
    resp = await adapter.generate(
        base_url="http://ollama:11434", api_key=None,
        model_id="llama3.1", messages=[{"role": "user", "content": "x"}],
        tools=build_tool_schemas(), temperature=0.2, top_p=1.0, max_tokens=512,
    )

    assert isinstance(resp, LLMToolCall)
    assert resp.tool == "final_answer"
    assert resp.arguments == {"answer": "X is a thing"}


@pytest.mark.asyncio
async def test_ollama_returns_text_when_tool_calls_is_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "llama3.1",
                "message": {
                    "role": "assistant",
                    "content": "fallback text",
                    "tool_calls": [],
                },
                "done": True,
            },
        )

    adapter = OllamaLLMAdapter(transport=_mock_transport(handler))
    resp = await adapter.generate(
        base_url="http://ollama:11434", api_key=None,
        model_id="llama3.1", messages=[{"role": "user", "content": "x"}],
        tools=None, temperature=0.2, top_p=1.0, max_tokens=128,
    )
    assert isinstance(resp, LLMTextResponse)
    assert resp.text == "fallback text"


@pytest.mark.asyncio
async def test_ollama_raises_llm_error_on_http_500() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    adapter = OllamaLLMAdapter(transport=_mock_transport(handler))
    with pytest.raises(LLMError):
        await adapter.generate(
            base_url="http://ollama:11434", api_key=None,
            model_id="llama3.1", messages=[{"role": "user", "content": "x"}],
            tools=None, temperature=0.2, top_p=1.0, max_tokens=128,
        )


@pytest.mark.asyncio
async def test_ollama_raises_llm_timeout_error_on_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    adapter = OllamaLLMAdapter(transport=_mock_transport(handler))
    with pytest.raises(LLMTimeoutError):
        await adapter.generate(
            base_url="http://ollama:11434", api_key=None,
            model_id="llama3.1", messages=[{"role": "user", "content": "x"}],
            tools=None, temperature=0.2, top_p=1.0, max_tokens=128,
        )


@pytest.mark.asyncio
async def test_ollama_raises_llm_error_on_malformed_response() -> None:
    """Body is JSON but doesn't have the expected `message` field."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"oops": "no message field"})

    adapter = OllamaLLMAdapter(transport=_mock_transport(handler))
    with pytest.raises(LLMError):
        await adapter.generate(
            base_url="http://ollama:11434", api_key=None,
            model_id="llama3.1", messages=[{"role": "user", "content": "x"}],
            tools=None, temperature=0.2, top_p=1.0, max_tokens=128,
        )


@pytest.mark.asyncio
async def test_ollama_omits_tools_field_when_none() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "x"},
                "done": True,
            },
        )

    adapter = OllamaLLMAdapter(transport=_mock_transport(handler))
    await adapter.generate(
        base_url="http://ollama:11434", api_key=None,
        model_id="llama3.1", messages=[{"role": "user", "content": "x"}],
        tools=None, temperature=0.2, top_p=1.0, max_tokens=128,
    )

    # When tools is None we MUST NOT send a `tools: null` field — some
    # Ollama versions reject it. Omit the key entirely.
    assert "tools" not in captured["body"]
```

- [ ] **Step 2.2: Run, confirm collection failure**

```bash
pytest tests/unit/test_ollama_llm_adapter.py -v
```

Expected: collection error — `ollama` module does not exist.

- [ ] **Step 2.3: Create `backend/src/tfm_rag/infrastructure/llm_providers/__init__.py`**

Empty package marker:

```python
```

- [ ] **Step 2.4: Create `backend/src/tfm_rag/infrastructure/llm_providers/ollama.py`**

```python
import json
import logging
from typing import Any

import httpx

from tfm_rag.domain.errors.chat import LLMError, LLMTimeoutError
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMResponse,
    LLMTextResponse,
    LLMToolCall,
)

_log = logging.getLogger(__name__)


class OllamaLLMAdapter:
    """LLMProvider for Ollama's /api/chat with tool calling.

    Tool calling is supported by Ollama 0.4+ for llama3.1, mistral-nemo,
    and a growing list of models. The request shape mirrors OpenAI's
    Chat Completions (messages + tools); the response includes a
    `message.tool_calls` array when the model decided to invoke a tool.

    `transport` is an optional httpx Transport for testing (MockTransport
    in unit tests). When omitted, httpx uses its default async transport.
    """

    DEFAULT_TIMEOUT_SECS = 300.0

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float | None = None,
    ) -> None:
        self._transport = transport
        self._timeout = timeout or self.DEFAULT_TIMEOUT_SECS

    async def generate(
        self,
        *,
        base_url: str,
        api_key: str | None,  # noqa: ARG002 — Ollama is keyless
        model_id: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None,
        temperature: float,
        top_p: float,
        max_tokens: int,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "num_predict": max_tokens,
            },
        }
        if tools is not None:
            body["tools"] = tools

        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                r = await client.post("/api/chat", json=body)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"Ollama /api/chat timed out after {self._timeout}s "
                f"(model={model_id!r})"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(
                f"Ollama /api/chat transport failed (model={model_id!r}): {exc}"
            ) from exc

        if r.status_code != 200:
            raise LLMError(
                f"Ollama /api/chat returned HTTP {r.status_code}: {r.text[:500]}"
            )

        try:
            payload = r.json()
        except json.JSONDecodeError as exc:
            raise LLMError(
                f"Ollama /api/chat returned non-JSON body: {r.text[:200]}"
            ) from exc

        message = payload.get("message")
        if not isinstance(message, dict):
            raise LLMError(
                f"Ollama /api/chat returned no `message` field; got keys "
                f"{list(payload)}"
            )

        tool_calls = message.get("tool_calls")
        if tool_calls:
            first = tool_calls[0]
            fn = first.get("function") or {}
            name = fn.get("name")
            if not isinstance(name, str):
                raise LLMError(
                    f"Ollama tool_call missing string `name`: {first!r}"
                )
            raw_args = fn.get("arguments", {})
            # Ollama returns arguments either as a dict or as a JSON string;
            # normalise to dict so the use case doesn't have to care.
            if isinstance(raw_args, str):
                try:
                    arguments: dict[str, Any] = json.loads(raw_args)
                except json.JSONDecodeError as exc:
                    raise LLMError(
                        f"Ollama tool_call arguments were a string but not "
                        f"valid JSON: {raw_args!r}"
                    ) from exc
            elif isinstance(raw_args, dict):
                arguments = raw_args
            else:
                raise LLMError(
                    f"Ollama tool_call arguments had unexpected type "
                    f"{type(raw_args).__name__}: {raw_args!r}"
                )
            return LLMToolCall(tool=name, arguments=arguments)

        content = message.get("content")
        if not isinstance(content, str):
            raise LLMError(
                f"Ollama message had no tool_calls and no string content: "
                f"{message!r}"
            )
        return LLMTextResponse(text=content)
```

- [ ] **Step 2.5: Run the adapter tests, expect 8 PASSED**

```bash
pytest tests/unit/test_ollama_llm_adapter.py -v
```

Expected: **8 PASSED**.

- [ ] **Step 2.6: Write failing tests for `LLMDispatcher`**

Create `backend/tests/unit/test_llm_dispatcher.py`:

```python
import pytest

from tfm_rag.domain.errors.chat import UnsupportedProviderError
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher
from tfm_rag.infrastructure.llm_providers.ollama import OllamaLLMAdapter


def test_for_provider_returns_registered_adapter() -> None:
    ollama = OllamaLLMAdapter()
    disp = LLMDispatcher({"ollama": ollama})
    assert disp.for_provider("ollama") is ollama


def test_for_provider_raises_for_unknown() -> None:
    disp = LLMDispatcher({"ollama": OllamaLLMAdapter()})
    with pytest.raises(UnsupportedProviderError):
        disp.for_provider("openai")


def test_default_registers_ollama_only() -> None:
    disp = LLMDispatcher.default()
    assert disp.for_provider("ollama") is not None
    with pytest.raises(UnsupportedProviderError):
        disp.for_provider("openai")
```

- [ ] **Step 2.7: Create `backend/src/tfm_rag/infrastructure/llm_providers/dispatcher.py`**

```python
from tfm_rag.domain.errors.chat import UnsupportedProviderError
from tfm_rag.domain.ports.llm import LLMProvider
from tfm_rag.infrastructure.llm_providers.ollama import OllamaLLMAdapter


class LLMDispatcher:
    """Routes (`provider_id` → `LLMProvider`).

    Symmetric to `EmbedderDispatcher`. Plan #15 wires only `ollama`;
    `openai` and `openai_compat` adapters land in follow-up plans.
    """

    def __init__(self, registry: dict[str, LLMProvider]) -> None:
        self._registry = registry

    def for_provider(self, provider_id: str) -> LLMProvider:
        adapter = self._registry.get(provider_id)
        if adapter is None:
            raise UnsupportedProviderError(
                f"No LLMProvider registered for provider_id={provider_id!r}. "
                f"Available: {sorted(self._registry)}"
            )
        return adapter

    @classmethod
    def default(cls) -> "LLMDispatcher":
        return cls({"ollama": OllamaLLMAdapter()})
```

- [ ] **Step 2.8: Run the dispatcher tests, expect 3 PASSED**

```bash
pytest tests/unit/test_llm_dispatcher.py -v
```

Expected: **3 PASSED**.

- [ ] **Step 2.9: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/llm_providers/__init__.py backend/src/tfm_rag/infrastructure/llm_providers/ollama.py backend/src/tfm_rag/infrastructure/llm_providers/dispatcher.py backend/tests/unit/test_ollama_llm_adapter.py backend/tests/unit/test_llm_dispatcher.py
git commit -m "feat(infra): OllamaLLMAdapter + LLMDispatcher (tool calling via /api/chat)"
```

---

## Task 3 — Application: `answer_query` agent loop + unit tests

**Files:**
- Create: `backend/src/tfm_rag/application/chat/answer_query.py`
- Create: `backend/tests/unit/test_answer_query.py`

- [ ] **Step 3.1: Write failing tests for the agent loop**

Create `backend/tests/unit/test_answer_query.py`:

```python
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tfm_rag.application.chat.answer_query import AnswerView, answer_query
from tfm_rag.domain.catalog.agent_tools import (
    TOOL_ABSTAIN,
    TOOL_FINAL_ANSWER,
    TOOL_SEARCH_DOCS,
)
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMTextResponse,
    LLMToolCall,
)
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk
from tfm_rag.infrastructure.persistence.repository import RequestContext


def _ctx() -> RequestContext:
    return RequestContext(tenant_id=uuid4(), user_id=uuid4())


def _chunk(text: str, source: str = "manual.pdf", idx: int = 0) -> RetrievedChunk:
    return RetrievedChunk(
        point_id=f"pid-{text}-{idx}",
        content=text,
        source_id=uuid4(),
        source_filename=source,
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
    row.system_prompt = "You are a helpful assistant."
    row.llm_selection = {
        "provider_id": "ollama",
        "credential_id": str(uuid4()),
        "model_id": "llama3.1",
    }
    row.pipeline_config = PipelineConfig.default().to_dict()
    row.widget_config = {}
    return row


def _chatbot_repo(row: MagicMock) -> MagicMock:
    repo = MagicMock()
    repo.get = AsyncMock(return_value=row)
    repo.list_kb_ids = AsyncMock(return_value=[uuid4()])
    return repo


def _fake_settings() -> MagicMock:
    s = MagicMock()
    s.ollama_base_url = "http://ollama:11434"
    return s


class _ScriptedLLM:
    """LLMProvider fake that returns the next response from a script."""

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._script.pop(0)


@pytest.mark.asyncio
async def test_answer_query_one_iteration_with_search_then_final() -> None:
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_SEARCH_DOCS, arguments={"query": "what is X"}),
        LLMToolCall(tool=TOOL_FINAL_ANSWER, arguments={"answer": "X is a thing."}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    chunks = [_chunk("X is described here.")]
    retrieve = AsyncMock(return_value=chunks)

    captured_msgs: list[dict[str, Any]] = []

    async def fake_create_session(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_append_message(*args: Any, **kwargs: Any) -> Any:
        captured_msgs.append(kwargs)
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        return None

    db = MagicMock()
    view = await answer_query(
        db, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: MagicMock(),
        llm_dispatcher=dispatcher,
        retrieve_docs=retrieve,
        create_session=fake_create_session,
        append_message=fake_append_message,
        touch_session=fake_touch,
        qdrant=MagicMock(),
        embedder_dispatcher=MagicMock(),
        settings=_fake_settings(),
        chatbot_id=row.id,
        session_id=None,
        user_message="what is X?",
    )

    assert isinstance(view, AnswerView)
    assert view.content == "X is a thing."
    assert len(view.iterations) == 2
    assert view.iterations[0].tool == TOOL_SEARCH_DOCS
    assert view.iterations[0].num_chunks == 1
    assert view.iterations[1].tool == TOOL_FINAL_ANSWER
    assert len(view.citations) == 1
    assert view.citations[0].source_name == "manual.pdf"

    # Two messages were appended: user, then assistant.
    assert len(captured_msgs) == 2
    assert captured_msgs[0]["role"] == "user"
    assert captured_msgs[0]["content"] == "what is X?"
    assert captured_msgs[1]["role"] == "assistant"
    assert captured_msgs[1]["content"] == "X is a thing."
    # citations and metadata.iterations were persisted as dicts (JSONB shape)
    persisted = captured_msgs[1]
    assert isinstance(persisted["citations"], list)
    assert persisted["citations"][0]["source_name"] == "manual.pdf"
    assert "iterations" in persisted["metadata"]
    assert len(persisted["metadata"]["iterations"]) == 2

    # retrieve was called with the LLM-supplied query, not the user message
    retrieve.assert_awaited_once()
    rcall = retrieve.await_args
    assert rcall.kwargs["query"] == "what is X"


@pytest.mark.asyncio
async def test_answer_query_abstain_branch() -> None:
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_ABSTAIN, arguments={"reason": "no docs match"}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    appended: list[dict[str, Any]] = []

    async def fake_append(*args: Any, **kwargs: Any) -> Any:
        appended.append(kwargs)
        return uuid4()

    async def fake_create(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        return None

    db = MagicMock()
    view = await answer_query(
        db, ctx,
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
        user_message="something obscure",
    )

    # On abstain, content carries the abstain reason and citations is empty
    assert "no docs match" in view.content.lower()
    assert view.citations == []
    assert view.iterations[-1].tool == TOOL_ABSTAIN

    assistant_msg = appended[-1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["citations"] == []


@pytest.mark.asyncio
async def test_answer_query_max_iterations_synthesises_abstain() -> None:
    """If the LLM never emits a terminal tool, we cap at
    max_retrieval_iterations and synthesise an abstain message rather
    than looping forever.
    """
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    # Force max_retrieval_iterations = 2
    pipe = PipelineConfig.from_dict(row.pipeline_config)
    pipe = PipelineConfig(
        top_k=pipe.top_k,
        score_threshold=pipe.score_threshold,
        agentic_mode=True,
        max_retrieval_iterations=2,
        enable_reranker=False,
        reranker_initial_top_k=30,
        abstain_when_insufficient=True,
        router_llm_selection=None,
        generation=pipe.generation,
    )
    row.pipeline_config = pipe.to_dict()
    chatbot_repo = _chatbot_repo(row)

    # LLM always asks for more searches — never emits final_answer/abstain.
    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_SEARCH_DOCS, arguments={"query": "q1"}),
        LLMToolCall(tool=TOOL_SEARCH_DOCS, arguments={"query": "q2"}),
        # A third call would happen if the loop didn't cap — script empty
        # would crash the test if we hit it.
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    async def fake_append(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_create(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        return None

    db = MagicMock()
    view = await answer_query(
        db, ctx,
        chatbot_repo_factory=lambda s, c: chatbot_repo,
        kb_repo_factory=lambda s, c: MagicMock(),
        llm_dispatcher=dispatcher,
        retrieve_docs=AsyncMock(return_value=[_chunk("noise")]),
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

    # The loop made exactly 2 LLM calls (max iterations)
    assert len(llm.calls) == 2
    # Synthesised abstain
    assert view.iterations[-1].tool == TOOL_ABSTAIN
    assert "max iterations" in view.content.lower()


@pytest.mark.asyncio
async def test_answer_query_text_response_treated_as_final() -> None:
    """If the LLM ignores the tool schema and returns raw text, we treat
    that as an implicit final_answer rather than crashing.
    """
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    llm = _ScriptedLLM([LLMTextResponse(text="here is your answer")])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    async def fake_append(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_create(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        return None

    db = MagicMock()
    view = await answer_query(
        db, ctx,
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

    assert view.content == "here is your answer"
    assert view.iterations[-1].tool == TOOL_FINAL_ANSWER
    assert view.citations == []


@pytest.mark.asyncio
async def test_answer_query_raises_when_chatbot_missing() -> None:
    ctx = _ctx()
    chatbot_repo = MagicMock()
    chatbot_repo.get = AsyncMock(side_effect=NotFoundError("nope"))
    chatbot_repo.list_kb_ids = AsyncMock(return_value=[])

    async def fake_unused(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("should not be called")

    db = MagicMock()
    with pytest.raises(ChatbotNotFoundError):
        await answer_query(
            db, ctx,
            chatbot_repo_factory=lambda s, c: chatbot_repo,
            kb_repo_factory=lambda s, c: MagicMock(),
            llm_dispatcher=MagicMock(),
            retrieve_docs=fake_unused,
            create_session=fake_unused,
            append_message=fake_unused,
            touch_session=fake_unused,
            qdrant=MagicMock(),
            embedder_dispatcher=MagicMock(),
            settings=_fake_settings(),
            chatbot_id=uuid4(),
            session_id=None,
            user_message="x",
        )


@pytest.mark.asyncio
async def test_answer_query_reuses_existing_session_when_id_passed() -> None:
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_FINAL_ANSWER, arguments={"answer": "ok"}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    existing_session = uuid4()
    create_calls = 0

    async def fake_create(*args: Any, **kwargs: Any) -> Any:
        nonlocal create_calls
        create_calls += 1
        return uuid4()

    async def fake_append(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        return None

    db = MagicMock()
    view = await answer_query(
        db, ctx,
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
        session_id=existing_session,
        user_message="x",
    )

    assert view.session_id == existing_session
    assert create_calls == 0


@pytest.mark.asyncio
async def test_answer_query_deduplicates_citations_across_iterations() -> None:
    """If two search_docs calls return overlapping chunks (same point_id),
    citations should not be duplicated.
    """
    ctx = _ctx()
    row = _chatbot_row(ctx.tenant_id)
    chatbot_repo = _chatbot_repo(row)

    shared = _chunk("repeated", idx=0)

    llm = _ScriptedLLM([
        LLMToolCall(tool=TOOL_SEARCH_DOCS, arguments={"query": "q1"}),
        LLMToolCall(tool=TOOL_SEARCH_DOCS, arguments={"query": "q2"}),
        LLMToolCall(tool=TOOL_FINAL_ANSWER, arguments={"answer": "a"}),
    ])
    dispatcher = MagicMock()
    dispatcher.for_provider = MagicMock(return_value=llm)

    # Both calls return the same chunk
    retrieve_results = [[shared], [shared]]

    async def fake_retrieve(*args: Any, **kwargs: Any) -> Any:
        return retrieve_results.pop(0)

    async def fake_append(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_create(*args: Any, **kwargs: Any) -> Any:
        return uuid4()

    async def fake_touch(*args: Any, **kwargs: Any) -> None:
        return None

    db = MagicMock()
    view = await answer_query(
        db, ctx,
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

    assert len(view.citations) == 1
    assert view.citations[0].chunk_id == shared.point_id
```

- [ ] **Step 3.2: Run, confirm collection failure**

```bash
pytest tests/unit/test_answer_query.py -v
```

Expected: collection error — `answer_query` module does not exist.

- [ ] **Step 3.3: Create `backend/src/tfm_rag/application/chat/answer_query.py`**

```python
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.chat.retrieve_docs import retrieve_docs as _real_retrieve_docs
from tfm_rag.application.chat.create_session import create_session as _real_create_session
from tfm_rag.application.chat.append_message import append_message as _real_append_message
from tfm_rag.application.chat.touch_session import touch_session as _real_touch_session
from tfm_rag.domain.catalog.agent_tools import (
    TOOL_ABSTAIN,
    TOOL_FINAL_ANSWER,
    TOOL_SEARCH_DOCS,
    build_tool_schemas,
)
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.value_objects.citation import Citation
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import PipelineConfig
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMTextResponse,
    LLMToolCall,
    RetrievalIteration,
)
from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher
from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
    ChatbotRepository,
)
from tfm_rag.infrastructure.persistence.repositories.knowledge_bases_repo import (
    KnowledgeBaseRepository,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

_log = logging.getLogger(__name__)

ChatbotRepoFactory = Callable[
    [AsyncSession, RequestContext], ChatbotRepository
]
KbRepoFactory = Callable[
    [AsyncSession, RequestContext], KnowledgeBaseRepository
]

# Helper signatures — exposed as injection points so unit tests can replace
# them with fakes that don't touch the DB or the network.
RetrieveDocs = Callable[..., Awaitable[list[RetrievedChunk]]]
CreateSession = Callable[..., Awaitable[UUID]]
AppendMessage = Callable[..., Awaitable[UUID]]
TouchSession = Callable[..., Awaitable[None]]


def _default_chatbot_repo(
    session: AsyncSession, ctx: RequestContext
) -> ChatbotRepository:
    return ChatbotRepository(session, ctx)


def _default_kb_repo(
    session: AsyncSession, ctx: RequestContext
) -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository(session, ctx)


@dataclass(frozen=True, slots=True)
class AnswerView:
    session_id: UUID
    message_id: UUID
    content: str
    citations: list[Citation]
    iterations: list[RetrievalIteration]


_SYSTEM_META_PROMPT = (
    "You have access to a knowledge base via the `search_docs` tool. "
    "Use it to ground your answer in the user's documents before "
    "responding with `final_answer`. If after a search you do not have "
    "the information needed, call `abstain` with a short reason rather "
    "than guessing."
)


def _build_system_message(chatbot_system_prompt: str) -> dict[str, Any]:
    parts = [chatbot_system_prompt.strip(), _SYSTEM_META_PROMPT]
    return {"role": "system", "content": "\n\n".join(p for p in parts if p)}


def _format_chunks_for_tool_result(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks as a single string the LLM can read as the
    tool result. We include filename + a short excerpt per chunk.
    """
    if not chunks:
        return "(no relevant documents found)"
    lines: list[str] = []
    for i, c in enumerate(chunks):
        body = c.content.strip().replace("\n", " ")
        if len(body) > 600:
            body = body[:600].rstrip() + "..."
        lines.append(f"[{i}] {c.source_filename}: {body}")
    return "\n".join(lines)


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
) -> AnswerView:
    """Agent-loop use case: answers `user_message` for `chatbot_id`,
    persisting both user + assistant turns to the session.

    Workflow:
      1. Load chatbot (tenant-scoped). Build LLMSelection + PipelineConfig.
      2. If no session_id, create a playground session.
      3. Append user message.
      4. Loop up to `max_retrieval_iterations`: ask LLM for a tool call.
         - `search_docs` → run retrieve_docs, accumulate chunks, append
           tool message to LLM context, loop.
         - `final_answer` → break with answer.
         - `abstain` → break with abstain reason as content.
         - text response → treat as implicit final_answer.
         - unknown tool → raise.
      5. If loop exhausted without a terminal decision, synthesise an
         abstain ("max iterations reached").
      6. Append assistant message with citations + iterations metadata.
      7. Touch the session.
    """
    # --- Step 1: load chatbot ---
    chatbot_repo = chatbot_repo_factory(session, ctx)
    try:
        row = await chatbot_repo.get(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc
    kb_ids = await chatbot_repo.list_kb_ids(chatbot_id)

    llm_selection = LLMSelection.from_dict(row.llm_selection)
    pipeline = PipelineConfig.from_dict(row.pipeline_config)
    system_prompt = row.system_prompt

    # --- Step 2: ensure a session exists ---
    if session_id is None:
        session_id = await create_session(
            session, ctx,
            chatbot_id=chatbot_id,
            origin="playground",
            public_session_cookie=None,
        )

    # --- Step 3: append user message ---
    await append_message(
        session, ctx,
        session_id=session_id,
        role="user",
        content=user_message,
        citations=None,
        metadata=None,
    )

    # --- Step 4: the agent loop ---
    llm = llm_dispatcher.for_provider(llm_selection.provider_id)
    # Ollama is SERVER_ENV: base_url from settings, no api_key. Other
    # providers (later plans) will resolve a credential here.
    base_url = settings.ollama_base_url
    api_key: str | None = None

    messages: list[dict[str, Any]] = [
        _build_system_message(system_prompt),
        {"role": "user", "content": user_message},
    ]
    tools = build_tool_schemas()

    seen_chunks: dict[str, RetrievedChunk] = {}
    iterations: list[RetrievalIteration] = []

    final_answer_text: str | None = None
    abstain_reason: str | None = None

    for i in range(pipeline.max_retrieval_iterations):
        t0 = time.perf_counter()
        resp = await llm.generate(
            base_url=base_url,
            api_key=api_key,
            model_id=llm_selection.model_id,
            messages=messages,
            tools=tools,
            temperature=pipeline.generation.temperature,
            top_p=pipeline.generation.top_p,
            max_tokens=pipeline.generation.max_tokens,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        if isinstance(resp, LLMTextResponse):
            final_answer_text = resp.text
            iterations.append(RetrievalIteration(
                index=i, tool=TOOL_FINAL_ANSWER,
                query=None, num_chunks=None, latency_ms=latency_ms,
            ))
            break

        if not isinstance(resp, LLMToolCall):  # pragma: no cover — exhaustiveness
            raise RuntimeError(f"Unexpected LLM response type: {type(resp).__name__}")

        if resp.tool == TOOL_FINAL_ANSWER:
            final_answer_text = str(resp.arguments.get("answer", ""))
            iterations.append(RetrievalIteration(
                index=i, tool=TOOL_FINAL_ANSWER,
                query=None, num_chunks=None, latency_ms=latency_ms,
            ))
            break

        if resp.tool == TOOL_ABSTAIN:
            abstain_reason = str(resp.arguments.get("reason", "no reason given"))
            iterations.append(RetrievalIteration(
                index=i, tool=TOOL_ABSTAIN,
                query=None, num_chunks=None, latency_ms=latency_ms,
            ))
            break

        if resp.tool == TOOL_SEARCH_DOCS:
            query = str(resp.arguments.get("query", "")).strip()
            chunks = await retrieve_docs(
                session, ctx,
                qdrant=qdrant,
                dispatcher=embedder_dispatcher,
                settings=settings,
                kb_ids=kb_ids,
                query=query,
                top_k=pipeline.top_k,
                score_threshold=(
                    pipeline.score_threshold
                    if pipeline.score_threshold > 0.0
                    else None
                ),
            )
            for c in chunks:
                seen_chunks.setdefault(c.point_id, c)
            iterations.append(RetrievalIteration(
                index=i, tool=TOOL_SEARCH_DOCS,
                query=query, num_chunks=len(chunks), latency_ms=latency_ms,
            ))
            # Echo the assistant tool call + tool result into the
            # conversation so the LLM can see what it received.
            messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {"name": TOOL_SEARCH_DOCS, "arguments": resp.arguments},
                }],
            })
            messages.append({
                "role": "tool",
                "name": TOOL_SEARCH_DOCS,
                "content": _format_chunks_for_tool_result(chunks),
            })
            continue

        # Unknown tool — defensive: synthesise an abstain rather than crash.
        _log.warning(
            "answer_query: unknown tool %r returned by LLM; aborting loop",
            resp.tool,
        )
        abstain_reason = f"LLM requested unknown tool {resp.tool!r}"
        iterations.append(RetrievalIteration(
            index=i, tool=TOOL_ABSTAIN,
            query=None, num_chunks=None, latency_ms=latency_ms,
        ))
        break

    # --- Step 5: handle loop exhaustion ---
    if final_answer_text is None and abstain_reason is None:
        abstain_reason = (
            "Reached max iterations without a final answer. The chatbot "
            "couldn't ground a confident response in the knowledge base."
        )
        iterations.append(RetrievalIteration(
            index=len(iterations), tool=TOOL_ABSTAIN,
            query=None, num_chunks=None, latency_ms=0.0,
        ))

    # --- Step 6: prepare assistant message ---
    if final_answer_text is not None:
        assistant_content = final_answer_text
        citations = [Citation.from_chunk(c) for c in seen_chunks.values()]
    else:
        assert abstain_reason is not None
        assistant_content = f"I don't know: {abstain_reason}"
        citations = []

    metadata = {"iterations": [it.to_dict() for it in iterations]}
    message_id = await append_message(
        session, ctx,
        session_id=session_id,
        role="assistant",
        content=assistant_content,
        citations=[c.to_dict() for c in citations],
        metadata=metadata,
    )

    # --- Step 7: bump activity ---
    await touch_session(session, ctx, session_id=session_id)

    return AnswerView(
        session_id=session_id,
        message_id=message_id,
        content=assistant_content,
        citations=citations,
        iterations=iterations,
    )
```

- [ ] **Step 3.4: Run the unit tests, expect 7 PASSED**

```bash
pytest tests/unit/test_answer_query.py -v
```

Expected: **7 PASSED**.

- [ ] **Step 3.5: Run all new unit tests so far (Tasks 1 + 2 + 3), expect 33 PASSED**

```bash
pytest tests/unit/test_citation_vo.py tests/unit/test_retrieval_iteration_vo.py tests/unit/test_agent_tools_catalog.py tests/unit/test_ollama_llm_adapter.py tests/unit/test_llm_dispatcher.py tests/unit/test_answer_query.py -v
```

Expected: **33 PASSED** (3 + 5 + 7 + 8 + 3 + 7).

- [ ] **Step 3.6: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/application/chat/answer_query.py backend/tests/unit/test_answer_query.py
git commit -m "feat(chat): AnswerQuery agent loop (search_docs → final_answer / abstain)"
```

---

## Task 4 — API: `POST /api/chatbots/{chatbot_id}/chat`

**Files:**
- Modify: `backend/src/tfm_rag/infrastructure/api/routers/chatbots.py`

- [ ] **Step 4.1: Append the chat endpoint to `chatbots.py`**

Open `backend/src/tfm_rag/infrastructure/api/routers/chatbots.py`. Add the new imports (merge with the existing import block at the top — do not duplicate):

```python
from tfm_rag.application.chat.answer_query import AnswerView, answer_query
from tfm_rag.domain.errors.chat import LLMError, LLMTimeoutError
from tfm_rag.domain.value_objects.citation import Citation
from tfm_rag.domain.value_objects.retrieval_iteration import RetrievalIteration
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher
from tfm_rag.infrastructure.settings import Settings, get_settings
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore
```

Then add at the bottom of the file (after the existing `list_sessions_` route):

```python
# --- Chat endpoint ----------------------------------------------------------

class ChatIn(BaseModel):
    session_id: UUID | None = None
    message: str = Field(..., min_length=1, max_length=8000)


class _CitationOut(BaseModel):
    chunk_id: str
    source_id: str
    source_name: str
    location: str
    score: float

    @classmethod
    def from_vo(cls, c: Citation) -> "_CitationOut":
        return cls(
            chunk_id=c.chunk_id,
            source_id=str(c.source_id),
            source_name=c.source_name,
            location=c.location,
            score=c.score,
        )


class _IterationOut(BaseModel):
    index: int
    tool: str
    query: str | None
    num_chunks: int | None
    latency_ms: float

    @classmethod
    def from_vo(cls, it: RetrievalIteration) -> "_IterationOut":
        return cls(
            index=it.index, tool=it.tool, query=it.query,
            num_chunks=it.num_chunks, latency_ms=it.latency_ms,
        )


class ChatOut(BaseModel):
    session_id: str
    message_id: str
    content: str
    citations: list[_CitationOut]
    iterations: list[_IterationOut]

    @classmethod
    def from_view(cls, v: AnswerView) -> "ChatOut":
        return cls(
            session_id=str(v.session_id),
            message_id=str(v.message_id),
            content=v.content,
            citations=[_CitationOut.from_vo(c) for c in v.citations],
            iterations=[_IterationOut.from_vo(i) for i in v.iterations],
        )


@router.post("/{chatbot_id}/chat", response_model=ChatOut)
async def chat_(
    chatbot_id: UUID,
    body: ChatIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ChatOut:
    # Match the existing per-request pattern in knowledge_bases.py: create
    # QdrantStore here and close it in `finally`. Dispatchers are stateless
    # and rebuilt per-request (cheap — see EmbedderDispatcher.default()).
    qdrant = QdrantStore(settings.qdrant_url, settings.qdrant_api_key)
    try:
        view = await answer_query(
            session, ctx,
            llm_dispatcher=LLMDispatcher.default(),
            qdrant=qdrant,
            embedder_dispatcher=EmbedderDispatcher.default(),
            settings=settings,
            chatbot_id=chatbot_id,
            session_id=body.session_id,
            user_message=body.message,
        )
    except ChatbotNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IncompatibleEmbeddingsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LLMTimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        await qdrant.close()
    return ChatOut.from_view(view)
```

- [ ] **Step 4.2: Verify the app imports cleanly and the route is registered**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
python -c "
from tfm_rag.infrastructure.api.app import app
routes = [(r.path, list(r.methods or [])) for r in app.routes if hasattr(r, 'path')]
chat = [r for r in routes if '/chat' in r[0]]
print(chat)
"
```

Expected output includes:
```
[('/api/chatbots/{chatbot_id}/chat', ['POST'])]
```

- [ ] **Step 4.3: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/api/routers/chatbots.py
git commit -m "feat(api): POST /api/chatbots/{id}/chat (agent loop endpoint, non-streaming)"
```

---

## Task 5 — Integration test: end-to-end vs live Ollama

This is the demo-shaped test. It runs the full flow against Postgres + Qdrant + Ollama, exercising the actual `llama3.1` model. Slow (~30–60s), so marked `integration`.

**Files:**
- Create: `backend/tests/integration/test_chat_agent_loop_flow.py`

- [ ] **Step 5.1: Write the integration test**

Create `backend/tests/integration/test_chat_agent_loop_flow.py`:

```python
import asyncio

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

# Higher per-test timeout — Ollama llama3.1 cold-start + 1-2 generations
# can take ~30-60s on first run.
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


async def _ollama_cred_id(client: AsyncClient, token: str) -> str:
    r = await client.get(
        "/api/credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    return next(c for c in r.json() if c["provider_id"] == "ollama")["id"]


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

    for _ in range(120):  # up to 2 min
        await asyncio.sleep(1)
        r = await client.get(f"/api/ingestion-jobs/{job_id}", headers=h)
        assert r.status_code == 200
        if r.json()["status"] in {"done", "failed"}:
            assert r.json()["status"] == "done", r.json()
            return
    raise AssertionError(f"ingestion did not finish in 2 min: job={job_id}")


async def test_end_to_end_agent_loop_returns_grounded_answer(
    _clean_state: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=180.0) as client:
        token, _ = await _register(client, "demo-chat@example.com")
        h = {"Authorization": f"Bearer {token}"}
        cred_id = await _ollama_cred_id(client, token)

        # 1) Create a KB with the Ollama bge-m3 embedder
        r = await client.post(
            "/api/knowledge-bases", headers=h,
            json={
                "name": "DemoKB",
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
        assert r.status_code == 201, r.text
        kb_id = r.json()["id"]

        # 2) Ingest a short fact-laden doc
        body = (
            b"The Spanish Civil War lasted from July 17, 1936 until April 1, 1939. "
            b"It pitted the Republicans, who were loyal to the left-leaning Popular "
            b"Front government of the Second Spanish Republic, against the Nationalists, "
            b"a falangist, conservative, and largely Catholic group led by General "
            b"Francisco Franco. The Nationalists won the war. Franco then ruled Spain "
            b"as a dictator until his death in 1975.\n\n"
            b"Pineapples grow on a low plant in tropical climates."
        )
        await _ingest_doc(client, token, kb_id, body)

        # 3) Create a chatbot pointing at the KB, using Ollama llama3.1
        r = await client.post(
            "/api/chatbots", headers=h,
            json={
                "name": "HistoryBot",
                "system_prompt": (
                    "You are a concise history assistant. Always ground your "
                    "answers in the documents available via search_docs."
                ),
                "llm_selection": {
                    "provider_id": "ollama",
                    "credential_id": cred_id,
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
        assert r.status_code == 201, r.text
        chatbot_id = r.json()["id"]

        # 4) Ask a question
        r = await client.post(
            f"/api/chatbots/{chatbot_id}/chat", headers=h,
            json={
                "message": "When did the Spanish Civil War end?",
            },
        )
        assert r.status_code == 200, r.text
        body_out = r.json()

        # Basic shape
        assert "session_id" in body_out
        assert "message_id" in body_out
        assert isinstance(body_out["content"], str) and body_out["content"].strip()
        assert isinstance(body_out["citations"], list)
        assert isinstance(body_out["iterations"], list)

        # The answer should mention 1939 (the year the war ended).
        # We allow either the assistant to give a final answer or — if the
        # model is being unusually cautious — to abstain. But we DO want at
        # least one search_docs iteration to have happened (the loop worked).
        tools_used = [it["tool"] for it in body_out["iterations"]]
        assert "search_docs" in tools_used, (
            f"Loop did not call search_docs; iterations={body_out['iterations']}"
        )

        content_lower = body_out["content"].lower()
        is_final = any(
            it["tool"] == "final_answer" for it in body_out["iterations"]
        )
        if is_final:
            # Should mention either '1939' or 'april' (allow some flexibility
            # because llama3.1 phrasing varies run-to-run).
            assert "1939" in content_lower or "april" in content_lower, (
                f"Unexpected final answer: {body_out['content']!r}"
            )
            # And there must be at least one citation pointing at manual.txt
            assert body_out["citations"], "Final answer with no citations"
            assert any(
                c["source_name"] == "manual.txt" for c in body_out["citations"]
            )
        else:
            # Abstain path — acceptable but flag it
            print(f"NOTE: model abstained: {body_out['content']!r}")

        # 5) Follow-up turn re-uses the same session_id
        first_session = body_out["session_id"]
        r = await client.post(
            f"/api/chatbots/{chatbot_id}/chat", headers=h,
            json={
                "session_id": first_session,
                "message": "Who led the Nationalists?",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["session_id"] == first_session

        # 6) The session now has 4 messages (user/assistant × 2)
        r = await client.get(f"/api/sessions/{first_session}", headers=h)
        assert r.status_code == 200
        messages = r.json()["messages"]
        assert len(messages) == 4
        assert [m["role"] for m in messages] == [
            "user", "assistant", "user", "assistant"
        ]


async def test_chat_on_unknown_chatbot_returns_404(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, _ = await _register(client, "ghost-chat@example.com")
        h = {"Authorization": f"Bearer {token}"}

        r = await client.post(
            "/api/chatbots/00000000-0000-0000-0000-000000000000/chat",
            headers=h,
            json={"message": "hi"},
        )
        assert r.status_code == 404


async def test_chat_isolation_between_tenants(_clean_state: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        alice_token, _ = await _register(client, "alice-chat@example.com")
        bob_token, _ = await _register(client, "bob-chat@example.com")
        alice_cred = await _ollama_cred_id(client, alice_token)

        # Alice creates an empty-KB chatbot
        r = await client.post(
            "/api/knowledge-bases",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={
                "name": "EmptyKB",
                "embedding_selection": {
                    "provider_id": "ollama", "credential_id": alice_cred,
                    "model_id": "bge-m3", "dim": 1024,
                },
            },
        )
        kb_id = r.json()["id"]

        r = await client.post(
            "/api/chatbots",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={
                "name": "AliceBot",
                "system_prompt": "x",
                "llm_selection": {
                    "provider_id": "ollama", "credential_id": alice_cred,
                    "model_id": "llama3.1",
                },
                "kb_ids": [kb_id],
                "widget_config": {},
            },
        )
        chatbot_id = r.json()["id"]

        # Bob tries to chat with Alice's chatbot → 404
        r = await client.post(
            f"/api/chatbots/{chatbot_id}/chat",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={"message": "hi"},
        )
        assert r.status_code == 404
```

- [ ] **Step 5.2: Reset DB and run the new integration test (slow — Ollama generates)**

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
pytest tests/integration/test_chat_agent_loop_flow.py -m integration -v --timeout=300
```

Expected: **3 PASSED** (1 end-to-end + 1 404 + 1 isolation). The first test
prints either a final answer mentioning 1939 / april, or an abstain note
(both acceptable for the demo).

- [ ] **Step 5.3: Run the full integration suite to confirm no regressions**

```bash
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration -m integration -v --timeout=300
```

Expected: previous 25 + 3 new = **28 PASSED**.

- [ ] **Step 5.4: Commit + tag**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/tests/integration/test_chat_agent_loop_flow.py
git commit -m "test(chat): end-to-end agent loop vs live Ollama (grounded answer + cascade + isolation)"
git tag cap-15-chat-agent-loop
```

---

## Controller cleanup (post-subagent — NOT a task)

After all 5 tasks land, the controller (you) does the global lint pass:

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
ruff check . --fix
mypy src/
pytest tests/ -m "not integration"
```

If ruff applied autofixes, commit them as `chore(plan-15): ruff autofix` and
**move the `cap-15-chat-agent-loop` tag forward** to that cleanup commit (per
the project's tag convention — see handover §8 "Pendientes / riesgos").

```bash
git tag -f cap-15-chat-agent-loop <cleanup-commit-sha>
```

---

## What's next after plan #15

M3 demo is complete. Remaining plans (orthogonal to the demo):

- **Plan #9 (KB-DB-SOURCES)** — open M4. Read-only SQL connectors.
- **Plan #11 (CHATBOT-WIDGET-CONFIG)** — widget configuration on chatbot.
- **Plan #13 (CHAT-SQL-EXECUTION)** — wires `query_database` into the agent loop using the SQL sources from plan #9. Will flip `build_tool_schemas(include_query_database=True)` here.
- **Plan #16 (WIDGET-RUNTIME)** — public widget endpoint + cookie-based session bootstrap (uses the `public_session_cookie` column already present in `chat_sessions`).
- **Plan #17 (EVAL-RAGAS)** — evaluation harness (M7).

Possible small follow-ups before any of those:
- SSE streaming on `POST /api/chatbots/{id}/chat` — replace the JSON body with a token-by-token stream. The agent loop is already iteration-aware; this is mostly an FastAPI streaming wrapper plus an Ollama `/api/chat?stream=true` path.
- Reranker integration into the chat loop — read `pipeline.enable_reranker` and pass a reranker instance into `retrieve_docs`.
- Resolve the `_session_factory` global → `app.state.session_factory` lifespan refactor (documented in handover as a long-standing TODO).
