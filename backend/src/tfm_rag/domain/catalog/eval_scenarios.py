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
