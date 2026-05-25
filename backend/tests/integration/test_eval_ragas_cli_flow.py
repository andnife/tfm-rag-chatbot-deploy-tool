"""End-to-end test for the eval-ragas CLI.

Requires the live Docker stack (postgres + qdrant + ollama with llama3.1
+ bge-m3). The CLI is invoked via subprocess so the test exercises the
real entry point and process boundary.

NOTE: this is the slowest test in the repo (~3-6 minutes). It's marked
`integration` and only runs when explicitly selected.
"""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import tfm_rag.infrastructure.api.dependencies as _deps
from tfm_rag.infrastructure.api.app import app
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
async def _clean_state(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE chat_messages, chat_sessions, "
            "chatbot_knowledge_base, chatbots, ingestion_jobs, "
            "sources, knowledge_bases, provider_credentials, users, tenants "
            "RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()
    _deps._session_factory = None


async def _register(client: AsyncClient, email: str) -> tuple[str, str]:
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return body["token"], body["tenant_id"]


async def _ingest_doc(
    client: AsyncClient, token: str, kb_id: str, body: bytes
) -> None:
    h = {"Authorization": f"Bearer {token}"}
    upload = await client.post(
        f"/api/knowledge-bases/{kb_id}/sources/documents",
        headers=h,
        files={"file": ("manual.txt", body, "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    job_id = upload.json()["job_id"]
    for _ in range(120):
        await asyncio.sleep(1)
        r = await client.get(f"/api/ingestion-jobs/{job_id}", headers=h)
        if r.json()["status"] in {"done", "failed"}:
            assert r.json()["status"] == "done", r.json()
            return
    raise AssertionError("ingestion did not finish in 2 min")


async def test_eval_ragas_cli_produces_reports(
    _clean_state: None, tmp_path: Path,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=180.0) as client:
        token, tenant_id_str = await _register(client, "eval-cli@example.com")
        h = {"Authorization": f"Bearer {token}"}

        creds = (await client.get("/api/credentials", headers=h)).json()
        cred_id = next(c for c in creds if c["provider_id"] == "ollama")["id"]

        # 1) Create a KB with the Ollama bge-m3 embedder
        r = await client.post(
            "/api/knowledge-bases", headers=h,
            json={
                "name": "EvalKB",
                "embedding_selection": {
                    "provider_id": "ollama",
                    "credential_id": cred_id,
                    "model_id": "bge-m3",
                    "dim": 1024,
                },
                "chunking_config": {
                    "strategy": "fixed",
                    "chunk_size": 300,
                    "chunk_overlap": 50,
                },
            },
        )
        kb_id = r.json()["id"]

        # 2) Ingest a small fact-dense doc
        body = (
            b"The Spanish Civil War lasted from July 17, 1936 until April 1, 1939. "
            b"The Nationalists were led by General Francisco Franco. "
            b"Franco died in 1975, ending nearly four decades of dictatorship."
        )
        await _ingest_doc(client, token, kb_id, body)

        # 3) Create a chatbot
        r = await client.post(
            "/api/chatbots", headers=h,
            json={
                "name": "EvalBot",
                "system_prompt": (
                    "Answer concisely using search_docs to ground your answer."
                ),
                "llm_selection": {
                    "provider_id": "ollama", "credential_id": cred_id,
                    "model_id": "llama3.1",
                },
                "kb_ids": [kb_id],
                "pipeline_config": {
                    "top_k": 3,
                    "max_retrieval_iterations": 3,
                },
                "widget_config": {},
            },
        )
        chatbot_id = r.json()["id"]

        # 4) Write a tiny dataset
        dataset = tmp_path / "ds.jsonl"
        dataset.write_text(
            json.dumps({
                "question": "When did the Spanish Civil War end?",
                "ground_truth": "April 1, 1939.",
                "scenario": "doc_only",
                "metadata": {"difficulty": "easy"},
            }) + "\n" +
            json.dumps({
                "question": "Who led the Nationalists?",
                "ground_truth": "Francisco Franco.",
                "scenario": "doc_only",
                "metadata": {"difficulty": "easy"},
            }) + "\n",
            encoding="utf-8",
        )
        output_dir = tmp_path / "report-dir"

        # 5) Invoke the CLI via subprocess so we exercise the real entry point
        env = {
            **os.environ,
            "POSTGRES_URL": "postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag",
            "QDRANT_URL": "http://localhost:6333",
            "OLLAMA_BASE_URL": "http://localhost:11434",
            "JWT_SECRET": "1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA",
            "FERNET_KEY": "8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=",
            "STORAGE_LOCAL_PATH": "/tmp/tfm_rag_storage",
        }
        cmd = [
            sys.executable, "-m", "tfm_rag.cli.eval_ragas",
            "--chatbot-id", chatbot_id,
            "--tenant-id", tenant_id_str,
            "--dataset", str(dataset),
            "--scenario", "doc_only",
            "--output-dir", str(output_dir),
            "--verbose",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=600.0
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise AssertionError("eval-ragas CLI timed out after 10 min")
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")

        # 6) Verify CLI exited 0 + reports landed
        assert proc.returncode == 0, (
            f"CLI exited {proc.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        )
        report_json = output_dir / "report.json"
        report_md = output_dir / "report.md"
        assert report_json.exists()
        assert report_md.exists()

        data = json.loads(report_json.read_text(encoding="utf-8"))
        assert data["chatbot_name"] == "EvalBot"
        assert data["scenario_filter"] == "doc_only"
        assert data["summary"]["num_cases"] == 2
        # We allow some cases to score 0 (LLM judge variance), but the
        # pipeline must have completed without errors AND at least one
        # case must have produced an answer (predicted_answer non-null).
        assert data["summary"]["num_errors"] == 0
        answered = [
            c for c in data["cases"]
            if c.get("predicted_answer") and c["predicted_answer"].strip()
        ]
        assert len(answered) >= 1, (
            "No cases produced a non-empty answer; check the CLI stdout:\n"
            + stdout
        )

        # Markdown contains the summary table
        md = report_md.read_text(encoding="utf-8")
        assert "# Evaluation report — EvalBot" in md
        assert "| Metric | Score |" in md
