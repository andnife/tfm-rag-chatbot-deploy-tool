"""Value objects for a snapshot of a remote DB schema.

A snapshot is stored inside Source.payload as:
{
    "schema_snapshot": {
        "captured_at": "<iso8601>",
        "tables": [
            {"schema": "public", "name": "users",
             "columns": [{"name": "id", "data_type": "integer",
                          "nullable": false}, ...]},
            ...
        ]
    }
}

Plan #13 will read the snapshot to compose `query_database` system prompts.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ColumnSchema:
    name: str
    data_type: str  # 'integer', 'text', 'timestamp', 'varchar(255)', ...
    nullable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "data_type": self.data_type,
            "nullable": self.nullable,
        }


@dataclass(frozen=True, slots=True)
class TableSchema:
    schema: str  # 'public' for postgres default; db name for mysql
    name: str
    columns: tuple[ColumnSchema, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "name": self.name,
            "columns": [c.to_dict() for c in self.columns],
        }


@dataclass(frozen=True, slots=True)
class DatabaseSchemaSnapshot:
    captured_at: datetime
    tables: tuple[TableSchema, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at.isoformat(),
            "tables": [t.to_dict() for t in self.tables],
        }

    @property
    def table_count(self) -> int:
        return len(self.tables)
