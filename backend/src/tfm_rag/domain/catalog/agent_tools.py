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
            "Run a read-only SQL SELECT against ONE of the attached SQL "
            "databases. The system prompt lists every available "
            "`source_id` and the tables/columns each exposes. Use this "
            "tool when the user's question requires live data, counts, "
            "or aggregations over those tables. The system rejects any "
            "statement that isn't a single SELECT."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": (
                        "UUID of the DatabaseSource to query. Pick from "
                        "the SQL database list in the system prompt."
                    ),
                },
                "sql": {
                    "type": "string",
                    "description": (
                        "A single read-only SELECT statement. Avoid SELECT * "
                        "for large tables; project only the columns you need."
                    ),
                },
            },
            "required": ["source_id", "sql"],
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
