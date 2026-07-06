from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tfm_rag.application.knowledge.get_ingestion_job import get_ingestion_job
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import IngestionJobNotFoundError


class _FakeRepo:
    def __init__(self, job: object | None) -> None:
        self._job = job

    async def get_ingestion_job(self, job_id):  # noqa: ANN001, ANN201
        if self._job is None:
            raise NotFoundError("ingestion job not found")
        return self._job


@pytest.mark.asyncio
async def test_get_ingestion_job_includes_stage_and_items() -> None:
    job_id = uuid4()
    now = datetime.now(UTC)
    job = SimpleNamespace(
        id=job_id,
        source_id=uuid4(),
        status="running",
        progress=68,
        stage="embedding",
        items_done=12,
        items_total=40,
        error=None,
        started_at=now,
        finished_at=None,
    )
    view = await get_ingestion_job(jobs_repo=_FakeRepo(job), job_id=job_id)
    assert view.stage == "embedding"
    assert view.items_done == 12
    assert view.items_total == 40
    assert view.progress == 68


@pytest.mark.asyncio
async def test_get_ingestion_job_missing_raises() -> None:
    with pytest.raises(IngestionJobNotFoundError):
        await get_ingestion_job(jobs_repo=_FakeRepo(None), job_id=uuid4())
