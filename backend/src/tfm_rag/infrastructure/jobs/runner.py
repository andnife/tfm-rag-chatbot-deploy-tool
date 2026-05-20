import asyncio
import logging
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import BackgroundTasks

_log = logging.getLogger(__name__)

type JobCoroutine = Callable[[], Coroutine[Any, Any, None]]


class JobsRunner:
    """Thin wrapper around FastAPI BackgroundTasks.

    In MVP this is a near-no-op layer — its purpose is to provide a single
    seam for tests to swap out background execution (e.g. for a synchronous
    runner in unit tests), and to ensure exceptions inside coroutines are
    logged instead of silently swallowed by Starlette.
    """

    def __init__(self, background_tasks: BackgroundTasks) -> None:
        self._bg = background_tasks

    def schedule(self, coro: JobCoroutine) -> None:
        """Schedule `coro` to run after the current response is sent."""
        self._bg.add_task(self._safe_run, coro)

    @staticmethod
    async def _safe_run(coro: JobCoroutine) -> None:
        try:
            await coro()
        except Exception:  # noqa: BLE001
            _log.exception("Background job failed")


class InMemoryRunner:
    """Synchronous in-memory runner for tests. Runs the coroutine immediately."""

    def __init__(self) -> None:
        self.completed: list[JobCoroutine] = []

    def schedule(self, coro: JobCoroutine) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # We're inside a running event loop (e.g. pytest-asyncio).
            # Run the coroutine in a separate thread with its own event loop.
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro())
                future.result()
        else:
            asyncio.run(coro())
        self.completed.append(coro)
