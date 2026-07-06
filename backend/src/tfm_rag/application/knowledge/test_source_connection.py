from typing import Any

from tfm_rag.domain.entities.source import SourceType
from tfm_rag.domain.ports.source_connection_tester import (
    SOURCE_CONNECTION_TESTERS,
    SourceConnectionTestResult,
)


async def test_source_connection(
    *,
    spec_type: SourceType,
    spec: dict[str, Any],
) -> SourceConnectionTestResult:
    """Pre-attach connection test. Stateless — does NOT persist anything.

    Plan #7 ships an empty tester registry; plans #8 and #9 register the
    document and database testers respectively. Until then this returns a
    structured "tester not registered" result so the UI can render a
    meaningful error.
    """
    tester = SOURCE_CONNECTION_TESTERS.get(spec_type)
    if tester is None:
        return SourceConnectionTestResult(
            ok=False,
            error=(
                f"TESTER_NOT_REGISTERED: no connection tester is wired for "
                f"source type {spec_type!r} yet"
            ),
        )
    return await tester.test(spec)


test_source_connection.__test__ = False  # type: ignore[attr-defined]
