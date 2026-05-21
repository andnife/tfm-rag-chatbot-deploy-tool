from dataclasses import dataclass
from typing import Any, Protocol

from tfm_rag.domain.entities.source import SourceType


@dataclass(frozen=True, slots=True)
class SourceConnectionTestResult:
    ok: bool
    error: str | None
    details: dict[str, Any] | None = None


class SourceConnectionTester(Protocol):
    """Pre-attach tester for one SourceType. Implementations live in adapters.

    The `spec` dict has the same shape that `payload` will have once the
    Source is persisted, but the tester MUST NOT persist anything.
    """

    async def test(self, spec: dict[str, Any]) -> SourceConnectionTestResult: ...


# Registry populated by adapters at import time. Plans #8/#9 will register
# their testers here. Plan #7 leaves it empty on purpose.
SOURCE_CONNECTION_TESTERS: dict[SourceType, SourceConnectionTester] = {}
