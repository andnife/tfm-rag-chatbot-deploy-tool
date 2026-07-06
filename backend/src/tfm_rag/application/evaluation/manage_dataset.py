# backend/src/tfm_rag/application/evaluation/manage_dataset.py
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from tfm_rag.application.knowledge.create_knowledge_base import (
    KnowledgeBaseView,
    create_knowledge_base,
)
from tfm_rag.application.knowledge.delete_knowledge_base import (
    delete_knowledge_base,
)
from tfm_rag.domain.entities.eval_dataset import EvalDataset, EvalDatasetItemInput
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.ports.repositories import (
    EvalDatasetItemRepositoryPort,
    EvalDatasetRepositoryPort,
    KnowledgeBaseRepositoryPort,
    SourceRepositoryPort,
)
from tfm_rag.domain.ports.storage import Storage
from tfm_rag.domain.ports.vector_store import VectorStorePort
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.database_source_spec import DatabaseSourceSpec
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection
from tfm_rag.domain.value_objects.eval_dataset import EvalDatasetView, validate_row_fields

KbCreator = Callable[..., Awaitable[KnowledgeBaseView]]
KbDeleter = Callable[..., Awaitable[None]]


def _to_dataset_view(ds: EvalDataset, num_rows: int) -> EvalDatasetView:
    return EvalDatasetView(
        id=ds.id,
        tenant_id=ds.tenant_id,
        name=ds.name,
        description=ds.description,
        knowledge_base_id=ds.knowledge_base_id,
        db_schema_name=ds.db_schema_name,
        sql_seed_artifact=ds.sql_seed_artifact,
        status=ds.status,
        status_error=ds.status_error,
        num_rows=num_rows,
    )


async def create_eval_dataset(
    *,
    ds_repo: EvalDatasetRepositoryPort,
    kb_repo: KnowledgeBaseRepositoryPort,
    qdrant: VectorStorePort,
    tenant_id: UUID,
    kb_creator: KbCreator = create_knowledge_base,
    name: str,
    description: str | None,
    chunking_config: ChunkingConfig,
    embedding_selection: EmbeddingSelection,
) -> EvalDatasetView:
    name = name.strip()
    if not name:
        raise ValidationError("name must not be empty")
    if await ds_repo.find_dataset_by_name(name) is not None:
        raise ValidationError(f"Eval dataset named {name!r} already exists in tenant")

    kb = await kb_creator(
        kb_repo=kb_repo,
        qdrant=qdrant,
        tenant_id=tenant_id,
        name=f"[eval] {name}",
        description=f"Testing KB for eval dataset {name!r}",
        chunking_config=chunking_config,
        embedding_selection=embedding_selection,
    )

    # create_dataset commits internally (the KB was already committed by the
    # kb_creator above), mirroring the original create-KB-then-create-dataset
    # ordering.
    dataset = await ds_repo.create_dataset(
        name=name,
        description=description,
        knowledge_base_id=kb.id,
    )
    return _to_dataset_view(dataset, num_rows=0)


async def list_eval_datasets(
    *,
    ds_repo: EvalDatasetRepositoryPort,
    item_repo: EvalDatasetItemRepositoryPort,
) -> list[EvalDatasetView]:
    datasets = await ds_repo.list_datasets(limit=200)
    return [
        _to_dataset_view(d, num_rows=await item_repo.count_for_dataset(d.id))
        for d in datasets
    ]


async def get_eval_dataset(
    *,
    ds_repo: EvalDatasetRepositoryPort,
    item_repo: EvalDatasetItemRepositoryPort,
    dataset_id: UUID,
) -> EvalDatasetView:
    dataset = await ds_repo.get_dataset(dataset_id)
    return _to_dataset_view(
        dataset, num_rows=await item_repo.count_for_dataset(dataset_id)
    )


async def delete_eval_dataset(
    *,
    ds_repo: EvalDatasetRepositoryPort,
    kb_repo: KnowledgeBaseRepositoryPort,
    sources_repo: SourceRepositoryPort,
    qdrant: VectorStorePort,
    tenant_id: UUID,
    dataset_id: UUID,
    kb_deleter: KbDeleter = delete_knowledge_base,
) -> None:
    dataset = await ds_repo.get_dataset(dataset_id)
    # Stage the dataset-row DELETE first (flush-only) so it commits atomically
    # with the KB delete: kb_deleter commits internally, flushing both pending
    # operations in one transaction, eliminating the partial-failure window
    # where a crash could orphan the dataset row with a dangling
    # knowledge_base_id.
    await ds_repo.delete_dataset(dataset_id)
    if dataset.knowledge_base_id is not None:
        # delete_knowledge_base commits internally (via the KB repo, sharing the
        # request session) -> commits the staged dataset delete too, atomically.
        await kb_deleter(
            kb_repo=kb_repo,
            sources_repo=sources_repo,
            tenant_id=tenant_id,
            qdrant=qdrant,
            kb_id=dataset.knowledge_base_id,
        )
    # When there is no KB, the staged delete commits at request end via the
    # session dependency's end-of-request commit (the request's unit of work).


async def replace_dataset_rows(
    *,
    ds_repo: EvalDatasetRepositoryPort,
    item_repo: EvalDatasetItemRepositoryPort,
    dataset_id: UUID,
    parsed_rows: list[dict[str, Any]],
) -> EvalDatasetView:
    dataset = await ds_repo.get_dataset(dataset_id)  # tenant-scoped existence check

    # Validate every row and build the inputs BEFORE mutating anything
    # (all-or-nothing: a validation failure never touches the repo).
    items: list[EvalDatasetItemInput] = []
    for r in parsed_rows:
        validate_row_fields(
            question=str(r.get("question", "")),
            ground_truth=str(r.get("ground_truth", "")),
            scenario=str(r.get("scenario", "")),
            complexity=str(r.get("complexity", "")),
            sql_reference=r.get("sql_reference"),
        )
        items.append(
            EvalDatasetItemInput(
                question=str(r["question"]).strip(),
                ground_truth=str(r["ground_truth"]).strip(),
                scenario=str(r["scenario"]),
                complexity=str(r["complexity"]),
                reference_contexts=r.get("reference_contexts"),
                sql_reference=r.get("sql_reference"),
                source_doc=r.get("source_doc"),
            )
        )

    await item_repo.replace_dataset_rows(dataset_id, items)
    num_rows = await item_repo.count_for_dataset(dataset_id)
    return _to_dataset_view(dataset, num_rows=num_rows)


# ---------------------------------------------------------------------------
# Thin injected callable types (keeps process_dataset free of repo/encryptor
# wiring; the composition root binds the real implementations at call time).
#   SeedProvisioner: (*, dataset_id, seed_sql, host, port, admin_user,
#                     admin_password) -> schema_name
#   AttachDb:        (*, kb_id, spec) -> None
# ---------------------------------------------------------------------------
SeedProvisioner = Callable[..., Awaitable[str]]
AttachDb = Callable[..., Awaitable[None]]


async def process_dataset(
    *,
    ds_repo: EvalDatasetRepositoryPort,
    item_repo: EvalDatasetItemRepositoryPort,
    dataset_id: UUID,
    storage: Storage,
    seed_provisioner: SeedProvisioner,
    attach_db: AttachDb,
    mysql_cfg: dict[str, Any],
) -> EvalDatasetView:
    dataset = await ds_repo.get_dataset(dataset_id)

    await ds_repo.set_processing(dataset_id)

    try:
        schema: str | None = None
        if dataset.sql_seed_artifact:
            seed_sql = (await storage.load(dataset.sql_seed_artifact)).decode("utf-8")
            schema = await seed_provisioner(
                dataset_id=dataset.id,
                seed_sql=seed_sql,
                host=mysql_cfg["host"],
                port=mysql_cfg["port"],
                admin_user=mysql_cfg["admin_user"],
                admin_password=mysql_cfg["admin_password"],
            )
            spec = DatabaseSourceSpec(
                driver="mysql",
                host=mysql_cfg["host"],
                port=int(mysql_cfg["port"]),
                db_name=schema,
                username=mysql_cfg["admin_user"],
                password=mysql_cfg["admin_password"],
            )
            await attach_db(kb_id=dataset.knowledge_base_id, spec=spec)

        updated = await ds_repo.set_ready(dataset_id, db_schema_name=schema)
    except Exception as exc:  # noqa: BLE001 — record failure, then re-raise
        await ds_repo.set_failed(dataset_id, error=str(exc))
        raise

    num_rows = await item_repo.count_for_dataset(dataset_id)
    return _to_dataset_view(updated, num_rows=num_rows)


async def set_sql_seed(
    *,
    ds_repo: EvalDatasetRepositoryPort,
    item_repo: EvalDatasetItemRepositoryPort,
    dataset_id: UUID,
    seed_bytes: bytes,
    storage: Storage,
    tenant_id: UUID,
) -> EvalDatasetView:
    await ds_repo.get_dataset(dataset_id)  # existence check before storage write
    uri = await storage.save(
        tenant_id=tenant_id,
        source_id=dataset_id,
        filename="seed.sql",
        content=seed_bytes,
    )
    updated = await ds_repo.set_sql_seed_artifact(dataset_id, uri=uri)
    num_rows = await item_repo.count_for_dataset(dataset_id)
    return _to_dataset_view(updated, num_rows=num_rows)
