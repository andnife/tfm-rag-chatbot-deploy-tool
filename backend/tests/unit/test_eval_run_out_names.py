from datetime import UTC, datetime
from uuid import uuid4

from tfm_rag.infrastructure.api.routers.eval_runs import EvalRunOut


class _Row:
    def __init__(self, dataset_path=None, dataset_id=None):
        self.id = uuid4()
        self.chatbot_id = uuid4()
        self.dataset_id = dataset_id
        self.dataset_path = dataset_path
        self.scenario_filter = None
        self.judge_model = "m"
        self.status = "done"
        self.progress = 100
        self.report_dir = None
        self.error = None
        self.created_at = datetime.now(UTC)
        self.started_at = None
        self.finished_at = None
        self.tokens_gen_in = None
        self.tokens_gen_out = None
        self.tokens_judge_in = None
        self.tokens_judge_out = None


def test_from_row_carries_names_and_dataset_id() -> None:
    ds_id = uuid4()
    row = _Row(dataset_id=ds_id)
    out = EvalRunOut.from_row(row, chatbot_name="Bot A", dataset_name="DS 1")
    assert out.chatbot_name == "Bot A"
    assert out.dataset_name == "DS 1"
    assert out.dataset_id == str(ds_id)


def test_from_row_without_names_leaves_them_none() -> None:
    out = EvalRunOut.from_row(_Row())
    assert out.chatbot_name is None
    assert out.dataset_name is None
    assert out.dataset_id is None
