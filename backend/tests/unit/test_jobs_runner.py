import asyncio

import pytest

from tfm_rag.infrastructure.jobs.runner import InMemoryRunner


async def test_inmemory_runner_executes_coroutine() -> None:
    runner = InMemoryRunner()
    flag = {"ran": False}

    async def work() -> None:
        flag["ran"] = True

    runner.schedule(work)
    assert flag["ran"] is True
    assert len(runner.completed) == 1


async def test_inmemory_runner_runs_in_existing_loop() -> None:
    runner = InMemoryRunner()
    order: list[int] = []

    async def work() -> None:
        await asyncio.sleep(0)
        order.append(1)

    runner.schedule(work)
    order.append(2)
    assert order == [1, 2]
