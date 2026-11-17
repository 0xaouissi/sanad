"""Run the golden question set through the real retrieval + prompt + model
path and score it deterministically, exactly like the dashboard evaluation.

This is the command-line twin of app.services.evaluation.run_evaluation, but
it writes nothing to the dashboard eval state, conversations, cache or metrics.
Use it to compare models without touching the default configuration: override
LLM_MODEL / LLM_THINK in the environment.

Prerequisites: PostgreSQL + Ollama running, the demo company seeded
(`python -m app.eval.seed --password ...`), embeddings cached in HF_HOME.

Run from the repo root with the backend venv (default: Apache-2.0 Qwen3-4B):
  PYTHONIOENCODING=utf-8 backend/.venv/Scripts/python.exe scripts/run_golden.py

Compare the former research-licensed 3B default (opt-in override):
  LLM_MODEL=qwen2.5:3b-instruct-q4_K_M PYTHONIOENCODING=utf-8 \
    backend/.venv/Scripts/python.exe scripts/run_golden.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
# get_settings() reads backend/.env relative to the working directory.
os.chdir(BACKEND)

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.models import Company  # noqa: E402
from app.db.session import dispose_db, get_session_factory, init_db  # noqa: E402
from app.eval.golden import load_golden  # noqa: E402
from app.eval.scoring import score_case, summarize  # noqa: E402
from app.providers.embeddings import get_embedding_provider  # noqa: E402
from app.providers.llm import get_llm_provider  # noqa: E402
from app.providers.reranker import get_rerank_provider  # noqa: E402
from app.services.evaluation import _answer_case  # noqa: E402

DEMO_NAME = "Sanad Demo"


async def main() -> None:
    settings = get_settings()
    await init_db()
    cases = load_golden().cases
    embedder = get_embedding_provider()
    llm = get_llm_provider()
    reranker = get_rerank_provider()
    async with get_session_factory()() as session:
        company = (
            await session.execute(select(Company).where(Company.name == DEMO_NAME))
        ).scalar_one_or_none()
        if company is None:
            company = (await session.execute(select(Company).limit(1))).scalar_one_or_none()
    if company is None:
        print("No company found. Seed the demo first: python -m app.eval.seed --password ...")
        await dispose_db()
        return
    rerank_on = reranker is not None
    print(f"Company: {company.name} | model={settings.resolved_llm_model}")
    print(f"tier={settings.model_tier} | think={settings.llm_think} | rerank={rerank_on}")
    print(
        f"Thresholds: min={settings.retrieval_min_score} "
        f"off_topic={settings.retrieval_off_topic_score}\n"
    )
    results = []
    # A fresh session per case: a slow model can idle the connection long
    # enough for PostgreSQL to drop it mid-run.
    for case in cases:
        started = time.perf_counter()
        async with get_session_factory()() as session:
            answer, citations, kind = await _answer_case(
                session, company, case, embedder, llm, settings, reranker
            )
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        result = score_case(case, answer, citations, duration_ms, kind)
        results.append(result)
        failed = [name for name, ok in result.checks.items() if not ok]
        status = "PASS" if result.passed else "FAIL " + ",".join(failed)
        print(f"{case.id:22} {case.language} {case.category:13} {status}  kind={kind}")
        if not result.passed:
            print(f"    answer: {result.answer}")
    summary = summarize(results)
    print("\nSUMMARY " + json.dumps(summary, ensure_ascii=False))
    await dispose_db()


if __name__ == "__main__":
    asyncio.run(main())