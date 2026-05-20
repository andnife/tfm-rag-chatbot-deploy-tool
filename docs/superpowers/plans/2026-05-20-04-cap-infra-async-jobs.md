# CAP-INFRA-ASYNC-JOBS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide the foundation for asynchronous job tracking — the `IngestionJob` domain entity, a generic `JobsRunner` wrapper around `FastAPI BackgroundTasks`, and an in-memory status registry suitable for MVP. The actual `ingestion_jobs` table migration is deferred to plan #7 (`CAP-KB-LIFECYCLE`) because the `sources` table it foreign-keys to is created there.

**Architecture:** A `JobsRunner` accepts a coroutine + a job id and runs it in the background via `BackgroundTasks`. While the job runs it updates the row in a (future) `ingestion_jobs` table. For plan #4 we provide the entity, status enum, and the runner pattern; persistence comes online in plan #7.

**Tech Stack:** FastAPI BackgroundTasks. No new dependencies.

**Depends on:** Plan #1 (Settings), Plan #2 (TenantScopingMiddleware — runner reads tenant_id from ctx).

---

## File structure

**Created:**

```
backend/src/tfm_rag/
├── domain/
│   └── entities/
│       └── ingestion_job.py       # IngestionJob entity + IngestionStatus enum
├── infrastructure/
│   └── jobs/
│       ├── __init__.py
│       └── runner.py              # JobsRunner

backend/tests/unit/
└── test_jobs_runner.py
```

---

## Task 1 — Entity + status enum

### Step 1.1: Create `backend/src/tfm_rag/domain/entities/ingestion_job.py`

```python
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class IngestionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class IngestionJob:
    id: UUID
    source_id: UUID
    tenant_id: UUID
    status: IngestionStatus
    progress: int  # 0..100
    error: str | None
    started_at: datetime
    finished_at: datetime | None
```

### Step 1.2: Commit

```bash
git add backend/src/tfm_rag/domain/entities/ingestion_job.py
git commit -m "feat(domain): IngestionJob entity + IngestionStatus enum"
```

---

## Task 2 — `JobsRunner` + tests

### Step 2.1: Create `backend/src/tfm_rag/infrastructure/jobs/__init__.py` (empty)

### Step 2.2: Create `backend/src/tfm_rag/infrastructure/jobs/runner.py`

```python
import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeAlias

from fastapi import BackgroundTasks


_log = logging.getLogger(__name__)

JobCoroutine: TypeAlias = Callable[[], Awaitable[None]]


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
            asyncio.get_event_loop().run_until_complete(coro())
        except RuntimeError:
            # No running loop; create one
            asyncio.run(coro())
        self.completed.append(coro)
```

### Step 2.3: Create `backend/tests/unit/test_jobs_runner.py`

```python
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
```

### Step 2.4: Commit

```bash
git add backend/src/tfm_rag/infrastructure/jobs/ \
        backend/tests/unit/test_jobs_runner.py
git commit -m "feat(infra): JobsRunner around BackgroundTasks + InMemoryRunner for tests"
```

---

## Task 3 — Tag

```bash
git tag cap-04-infra-async-jobs
```

---

## Done criteria

- `IngestionJob` entity + `IngestionStatus` enum (queued/running/done/failed).
- `JobsRunner.schedule(coro)` wraps `BackgroundTasks.add_task` with exception logging.
- `InMemoryRunner` for tests runs the coroutine synchronously.
- Tag `cap-04-infra-async-jobs`.

## Deferred to plan #7

- The `ingestion_jobs` Postgres table + migration (depends on `sources` table).
- An `IngestionJobsRepository` (depends on the ORM model which needs the table).

## What plan #5 will build on top

Plan #5 (`CAP-AUTH-IDENTITY`) adds RegisterUser / LoginUser / LoginWithGoogle / BootstrapTenant — uses Plan #2's User/Tenant ORM + JWT helpers + Plan #3's Fernet (for hashing pass… wait, password hashing uses bcrypt not Fernet; Fernet only encrypts the Ollama default `ProviderCredential` row created by BootstrapTenant).
