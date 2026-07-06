from tfm_rag.infrastructure.persistence.models.eval_runs import EvalRunRow
from tfm_rag.infrastructure.persistence.repositories.eval_runs_repo import (
    EvalRunRepository,
)


def test_repo_targets_eval_run_row() -> None:
    assert EvalRunRepository.model is EvalRunRow
    assert hasattr(EvalRunRepository, "list_recent")
