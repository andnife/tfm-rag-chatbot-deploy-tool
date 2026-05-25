"""Unit tests for system_prompt.build_chatbot_system_prompt."""
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from tfm_rag.application.chat.system_prompt import build_chatbot_system_prompt


def _db_source(
    *,
    source_id: UUID | None = None,
    driver: str = "postgres",
    db_name: str = "shop",
    tables: list[tuple[str, str, list[tuple[str, str, bool]]]] | None = None,
) -> dict[str, Any]:
    """Build the SAME dict shape that SourcesRepository would return for
    a DatabaseSource (kb_id agnostic)."""
    src_id = source_id or uuid4()
    table_blocks = []
    for schema, table_name, cols in (tables or []):
        table_blocks.append({
            "schema": schema,
            "name": table_name,
            "columns": [
                {"name": c, "data_type": t, "nullable": n}
                for c, t, n in cols
            ],
        })
    return {
        "source_id": src_id,
        "type": "database",
        "payload": {
            "driver": driver,
            "host": "h", "port": 5432, "db_name": db_name,
            "username": "u", "password_encrypted": "Zm9v",
            "ssl_mode": "disable",
            "schema_snapshot": {
                "captured_at": datetime(2026, 5, 25, tzinfo=timezone.utc).isoformat(),
                "tables": table_blocks,
            },
        },
    }


def test_no_db_sources_returns_base_unchanged() -> None:
    out = build_chatbot_system_prompt("You are a helpful assistant.", db_sources=[])
    assert out == "You are a helpful assistant."


def test_with_one_db_source_appends_block() -> None:
    src = _db_source(
        driver="postgres", db_name="shop",
        tables=[
            ("public", "users", [
                ("id", "integer", False),
                ("email", "text", False),
            ]),
        ],
    )
    out = build_chatbot_system_prompt(
        "You are a helpful assistant.", db_sources=[src]
    )
    assert "You are a helpful assistant." in out
    assert "query_database" in out
    assert str(src["source_id"]) in out
    assert "public.users" in out
    assert "id integer" in out.lower() or "id (integer" in out.lower()


def test_with_multiple_sources_lists_all() -> None:
    s1 = _db_source(driver="postgres", db_name="a", tables=[
        ("public", "t1", [("x", "integer", False)]),
    ])
    s2 = _db_source(driver="mysql", db_name="b", tables=[
        ("b", "t2", [("y", "varchar", True)]),
    ])
    out = build_chatbot_system_prompt("BASE", db_sources=[s1, s2])
    assert str(s1["source_id"]) in out
    assert str(s2["source_id"]) in out
    assert "postgres" in out.lower()
    assert "mysql" in out.lower()
    assert "public.t1" in out
    assert "b.t2" in out


def test_excludes_document_sources() -> None:
    doc_src: dict[str, Any] = {
        "source_id": uuid4(),
        "type": "document",
        "payload": {"kind": "upload", "filename": "x.txt"},
    }
    db_src = _db_source(tables=[
        ("public", "users", [("id", "integer", False)])
    ])
    out = build_chatbot_system_prompt(
        "BASE", db_sources=[doc_src, db_src]
    )
    assert "x.txt" not in out  # documents NOT included
    assert "public.users" in out
