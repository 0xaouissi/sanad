"""Run the held-out question set through the real retrieval + prompt + model
path and score it deterministically, exactly like the golden evaluation.

The held-out questions (backend/app/eval/heldout.json) were NOT used to
calibrate the retrieval thresholds. This reports them SEPARATELY from the
golden set to show how refusals and grounding generalize to unseen phrasings.
It writes nothing to the dashboard eval state, conversations, cache or metrics.

Prerequisites: PostgreSQL + Ollama running, the demo company seeded
(`python -m app.eval.seed --password ...`), embeddings cached in HF_HOME.

Run from the repo root with the backend venv:
  PYTHONIOENCODING=utf-8 backend/.venv/Scripts/python.exe scripts/run_heldout.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
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
from app.eval.golden import GoldenSet  # noqa: E402
from app.eval.scoring import score_case, summarize  # noqa: E402
from app.providers.embeddings import get_embedding_provider  # noqa: E402
from app.providers.llm import get_llm_provider  # noqa: E402
from app.providers.reranker import get_rerank_provider  # noqa: E402
from app.services.evaluation import _answer_case  # noqa: E402

HELDOUT_PATH = BACKEND / "app" / "eval" / "heldout.json"
DEMO_NAME = "Sanad Demo"


async def main() -> None:
    settings = get_settings()
    await init_db()
    cases = GoldenSet.model_validate_json(HELDOUT_PATH.read_text(encoding="utf-8")).cases
    embedder = get_embedding_provider()
    llm = get_llm_provider()
    reranker = get_rerank_provider()
    results = []
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
        print(f"Company: {company.name} | tier={settings.model_tier} | rerank={rerank_on}")
        print(
            f"Thresholds: min={settings.retrieval_min_score} "
            f"off_topic={settings.retrieval_off_topic_score}\n"
        )
        for case in cases:
            answer, citations, kind = await _answer_case(
                session, company, case, embedder, llm, settings, reranker
            )
            result = score_case(case, answer, citations, 0.0, kind)
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