from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select

from tfm_rag.domain.entities.eval_dataset import (
    DatasetStatus,
    EvalDataset,
    EvalDatasetItem,
    EvalDatasetItemInput,
)
from tfm_rag.infrastructure.persistence.models.eval_datasets import (
    EvalDatasetItemRow,
    EvalDatasetRow,
)
from tfm_rag.infrastructure.persistence.repository import BaseRepository


class EvalDatasetRepository(BaseRepository[EvalDatasetRow]):
    model = EvalDatasetRow

    @staticmethod
    def _to_entity(row: EvalDatasetRow) -> EvalDataset:
        return EvalDataset(
            id=row.id,
            tenant_id=row.tenant_id,
            name=row.name,
            description=row.description,
            knowledge_base_id=row.knowledge_base_id,
            db_schema_name=row.db_schema_name,
            sql_seed_artifact=row.sql_seed_artifact,
            status=cast(DatasetStatus, row.status),
            status_error=row.status_error,
        )

    async def find_by_name(self, name: str) -> EvalDatasetRow | None:
        stmt = select(EvalDatasetRow).where(
            EvalDatasetRow.tenant_id == self._ctx.tenant_id,
            EvalDatasetRow.name == name,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    # --- entity-returning port methods ------------------------------------

    async def get_dataset(self, dataset_id: UUID) -> EvalDataset:
        return self._to_entity(await self.get(dataset_id))

    async def find_dataset_by_name(self, name: str) -> EvalDataset | None:
        row = await self.find_by_name(name)
        return self._to_entity(row) if row is not None else None

    async def list_datasets(self, *, limit: int) -> list[EvalDataset]:
        return [self._to_entity(r) for r in await self.list(limit=limit)]

    async def create_dataset(
        self,
        *,
        name: str,
        description: str | None,
        knowledge_base_id: UUID | None,
    ) -> EvalDataset:
        row = EvalDatasetRow(
            id=uuid4(),
            tenant_id=self._ctx.tenant_id,
            name=name,
            description=description,
            knowledge_base_id=knowledge_base_id,
            db_schema_name=None,
            sql_seed_artifact=None,
            status="draft",
            status_error=None,
        )
        await self.add(row)
        await self._session.commit()
        return self._to_entity(row)

    async def delete_dataset(self, dataset_id: UUID) -> None:
        # Stage the DELETE (BaseRepository.delete executes but does NOT commit)
        # so it commits atomically with the caller's other pending work.
        await self.delete(dataset_id)

    async def set_sql_seed_artifact(
        self, dataset_id: UUID, *, uri: str
    ) -> EvalDataset:
        row = await self.get(dataset_id)
        row.sql_seed_artifact = uri
        await self._session.commit()
        return self._to_entity(row)

    async def set_processing(self, dataset_id: UUID) -> None:
        row = await self.get(dataset_id)
        row.status = "processing"
        row.status_error = None
        await self._session.commit()

    async def set_ready(
        self, dataset_id: UUID, *, db_schema_name: str | None
    ) -> EvalDataset:
        row = await self.get(dataset_id)
        if db_schema_name is not None:
            row.db_schema_name = db_schema_name
        row.status = "ready"
        row.status_error = None
        await self._session.commit()
        return self._to_entity(row)

    async def set_failed(self, dataset_id: UUID, *, error: str) -> None:
        row = await self.get(dataset_id)
        row.status = "failed"
        row.status_error = error[:2000]
        await self._session.commit()


class EvalDatasetItemRepository(BaseRepository[EvalDatasetItemRow]):
    model = EvalDatasetItemRow

    @staticmethod
    def _to_entity(row: EvalDatasetItemRow) -> EvalDatasetItem:
        return EvalDatasetItem(
            id=row.id,
            tenant_id=row.tenant_id,
            dataset_id=row.dataset_id,
            ordinal=row.ordinal,
            question=row.question,
            ground_truth=row.ground_truth,
            scenario=row.scenario,
            complexity=row.complexity,
            reference_contexts=row.reference_contexts,
            sql_reference=row.sql_reference,
            source_doc=row.source_doc,
        )

    async def list_for_dataset(self, dataset_id: UUID) -> list[EvalDatasetItemRow]:
        stmt = (
            select(EvalDatasetItemRow)
            .where(
                EvalDatasetItemRow.tenant_id == self._ctx.tenant_id,
                EvalDatasetItemRow.dataset_id == dataset_id,
            )
            .order_by(EvalDatasetItemRow.ordinal)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_for_dataset(self, dataset_id: UUID) -> int:
        stmt = select(func.count()).where(
            EvalDatasetItemRow.tenant_id == self._ctx.tenant_id,
            EvalDatasetItemRow.dataset_id == dataset_id,
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def delete_for_dataset(self, dataset_id: UUID) -> None:
        stmt = delete(EvalDatasetItemRow).where(
            EvalDatasetItemRow.tenant_id == self._ctx.tenant_id,
            EvalDatasetItemRow.dataset_id == dataset_id,
        )
        await self._session.execute(stmt)

    # --- entity-returning port methods ------------------------------------

    async def list_items_by_dataset(
        self, dataset_id: UUID
    ) -> list[EvalDatasetItem]:
        return [self._to_entity(r) for r in await self.list_for_dataset(dataset_id)]

    async def replace_dataset_rows(
        self, dataset_id: UUID, items: list[EvalDatasetItemInput]
    ) -> None:
        await self.delete_for_dataset(dataset_id)
        for ordinal, item in enumerate(items):
            self._session.add(
                EvalDatasetItemRow(
                    id=uuid4(),
                    tenant_id=self._ctx.tenant_id,
                    dataset_id=dataset_id,
                    ordinal=ordinal,
                    question=item.question,
                    ground_truth=item.ground_truth,
                    scenario=item.scenario,
                    complexity=item.complexity,
                    reference_contexts=item.reference_contexts,
                    sql_reference=item.sql_reference,
                    source_doc=item.source_doc,
                )
            )
        await self._session.commit()
