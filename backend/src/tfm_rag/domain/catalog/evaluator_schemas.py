"""Structured-output tool schemas for the evaluator role (sub-proyecto B).

The evaluator emits its decisions by calling a SINGLE forced tool — there is
no free tool-loop. The LLM adapter already translates a tool call into
`LLMToolCall(tool, arguments)`.
"""
from typing import Any

from tfm_rag.domain.catalog.routes import (
    ROUTE_BOTH,
    ROUTE_DOCS,
    ROUTE_NORMAL,
    ROUTE_SQL,
)

# Minimum max_tokens for the forced tool-calls of the route/grade/sql steps.
# These reuse the chatbot's answer GenerationConfig, so a user who sets a small
# answer `max_tokens` (e.g. 32 for terse replies) would otherwise truncate the
# structured tool-call → it fails to parse → the pipeline silently abstains
# ("grader returned no valid verdict"). Floor the structured calls so they are
# never starved, independent of the answer length.
STRUCTURED_OUTPUT_MIN_TOKENS = 512

ROUTE_DECISION_TOOL = "route_decision"


def build_route_decision_schema(*, allow_sql: bool) -> list[dict[str, Any]]:
    """One tool the evaluator MUST call to classify the question.

    When `allow_sql` is False (B1), the route enum is restricted to
    `normal`/`docs` so the model cannot pick a route the orchestrator can't
    execute yet.
    """
    routes = [ROUTE_NORMAL, ROUTE_DOCS]
    if allow_sql:
        routes += [ROUTE_SQL, ROUTE_BOTH]
    return [{
        "type": "function",
        "function": {
            "name": ROUTE_DECISION_TOOL,
            "description": (
                "Classify the user's question into exactly one route. "
                "`normal` = greeting / small talk / meta-question about what "
                "the bot can do / clarification (no knowledge lookup). "
                "`docs` = anything factual answerable from the knowledge base."
                + (
                    " `sql` = needs live data from a SQL database. "
                    "`both` = needs documents AND SQL."
                    if allow_sql else ""
                )
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "route": {"type": "string", "enum": routes},
                    "rationale": {
                        "type": "string",
                        "description": "One short sentence justifying the route.",
                    },
                },
                "required": ["route", "rationale"],
            },
        },
    }]


GRADE_VERDICT_TOOL = "grade_verdict"


def build_grade_verdict_schema() -> list[dict[str, Any]]:
    """One tool the evaluator MUST call to judge whether the gathered context
    answers the question. `reformulated_query` (docs) / `fixed_sql` (sql) /
    `abstain_reason` are only meaningful when `sufficient` is False."""
    return [{
        "type": "function",
        "function": {
            "name": GRADE_VERDICT_TOOL,
            "description": (
                "Judge whether the provided context is enough to answer the "
                "user's question. If it is not, optionally suggest a better "
                "search query (reformulated_query), a corrected SQL query "
                "(fixed_sql), or give a short reason to abstain."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sufficient": {
                        "type": "boolean",
                        "description": "True if the context answers the question.",
                    },
                    "reformulated_query": {
                        "type": "string",
                        "description": "A better search query, if insufficient.",
                    },
                    "fixed_sql": {
                        "type": "string",
                        "description": "A corrected SELECT, if insufficient.",
                    },
                    "abstain_reason": {
                        "type": "string",
                        "description": "Short reason the question can't be answered.",
                    },
                },
                "required": ["sufficient"],
            },
        },
    }]


RUN_QUERY_TOOL = "run_query"


def build_run_query_schema() -> list[dict[str, Any]]:
    """The tool the sql_generator calls to run ONE read-only query. It calls it
    repeatedly (each result is fed back) to gather data, then STOPS by replying
    with plain text once it has enough. No explore/answer distinction."""
    return [{
        "type": "function",
        "function": {
            "name": RUN_QUERY_TOOL,
            "description": (
                "Run one READ-ONLY SELECT against a database source and get its "
                "result back. `source_id` MUST be one of the listed ids. No "
                "INSERT/UPDATE/DELETE/DDL. Call this again to gather more data "
                "(e.g. SELECT DISTINCT a text column to learn its real values "
                "before filtering — never assume a value's spelling/language). "
                "When you have enough data to answer, STOP calling it and reply "
                "with a short plain-text confirmation instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "The id of the database source to query.",
                    },
                    "sql": {
                        "type": "string",
                        "description": "A single READ-ONLY SELECT statement.",
                    },
                },
                "required": ["source_id", "sql"],
            },
        },
    }]
