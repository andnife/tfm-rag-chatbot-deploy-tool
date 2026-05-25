"""CLI entry point: ``python -m tfm_rag.cli.eval_ragas`` (or ``eval-ragas``
via the script entry in pyproject.toml).

Reads settings from .env (the same way the API does), builds a one-off
DB session, runs the eval pipeline, writes ``report.json`` + ``report.md``
to ``--output-dir`` (default: ``eval_runs/<UTC-timestamp>/``).
"""
import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from tfm_rag.application.evaluation.report_writer import write_report
from tfm_rag.application.evaluation.run_ragas_evaluation import (
    run_ragas_evaluation,
)
from tfm_rag.domain.catalog.eval_scenarios import KNOWN_SCENARIOS
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.evaluation import (
    EvaluationDatasetError,
    EvaluationError,
)
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.evaluation.ragas_evaluator import RagasEvaluator
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import get_settings
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

_log = logging.getLogger(__name__)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="eval-ragas",
        description=(
            "Run a RAGAS evaluation against a chatbot. Writes report.json "
            "+ report.md to --output-dir."
        ),
    )
    p.add_argument(
        "--chatbot-id", required=True, type=UUID,
        help="UUID of the chatbot to evaluate.",
    )
    p.add_argument(
        "--tenant-id", required=True, type=UUID,
        help=(
            "UUID of the tenant the chatbot belongs to. Required because "
            "the CLI runs without an auth middleware."
        ),
    )
    p.add_argument(
        "--dataset", required=True, type=Path,
        help="Path to the JSONL evaluation dataset.",
    )
    p.add_argument(
        "--scenario", default=None,
        choices=sorted(KNOWN_SCENARIOS),
        help="Filter dataset to entries with this scenario.",
    )
    p.add_argument(
        "--judge-model", default=None,
        help=(
            "Override the LLM used by RAGAS as judge. Defaults to the "
            "chatbot's own model_id (recommended for self-consistent runs)."
        ),
    )
    p.add_argument(
        "--embedding-model", default="bge-m3",
        help="Embedding model RAGAS uses for context_precision/recall.",
    )
    p.add_argument(
        "--output-dir", default=None, type=Path,
        help=(
            "Directory for report.json + report.md. Defaults to "
            "eval_runs/<UTC-timestamp>/."
        ),
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print one line per case as it runs.",
    )
    return p


def _print_progress(idx: int, total: int, status: str) -> None:
    print(f"[{idx}/{total}] {status}", flush=True)


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    output_dir = args.output_dir or Path(
        f"eval_runs/{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )

    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    qdrant = QdrantStore(settings.qdrant_url, settings.qdrant_api_key)
    try:
        async with factory() as db_session:
            ctx = RequestContext(tenant_id=args.tenant_id, user_id=None)

            # Resolve judge model: use chatbot's own model_id if no override.
            judge_model = args.judge_model
            if judge_model is None:
                # Peek the chatbot to learn its model. Done lazily here
                # rather than threading another arg into the use case.
                from tfm_rag.infrastructure.persistence.repositories.chatbots_repo import (
                    ChatbotRepository,
                )
                repo = ChatbotRepository(db_session, ctx)
                try:
                    row = await repo.get(args.chatbot_id)
                except Exception:
                    print(
                        f"error: chatbot {args.chatbot_id} not found in tenant "
                        f"{args.tenant_id}",
                        file=sys.stderr,
                    )
                    return 2
                judge_model = row.llm_selection["model_id"]

            evaluator = RagasEvaluator(
                base_url=settings.ollama_base_url,
                judge_model=judge_model,
                embedding_model=args.embedding_model,
            )

            report = await run_ragas_evaluation(
                db_session, ctx,
                evaluator=evaluator,
                qdrant=qdrant,
                embedder_dispatcher=EmbedderDispatcher.default(),
                llm_dispatcher=LLMDispatcher.default(),
                settings=settings,
                chatbot_id=args.chatbot_id,
                dataset_path=args.dataset,
                scenario_filter=args.scenario,
                progress=_print_progress if args.verbose else None,
            )

        paths = write_report(report, output_dir=output_dir)
        print(f"report.json: {paths.json_path}")
        print(f"report.md:   {paths.markdown_path}")
        print(
            f"Summary: {report.summary.num_scored}/{report.summary.num_cases} "
            f"scored, {report.summary.num_errors} errors."
        )
        for metric, value in sorted(report.summary.metrics.items()):
            print(f"  {metric:>20s}: {value:.3f}")
        return 0
    finally:
        await qdrant.close()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = _build_arg_parser()
    args = parser.parse_args()
    try:
        exit_code = asyncio.run(_run(args))
    except EvaluationDatasetError as exc:
        print(f"dataset error: {exc}", file=sys.stderr)
        sys.exit(2)
    except ChatbotNotFoundError as exc:
        print(f"chatbot not found: {exc}", file=sys.stderr)
        sys.exit(2)
    except EvaluationError as exc:
        print(f"evaluation error: {exc}", file=sys.stderr)
        sys.exit(3)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
