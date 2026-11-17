"""Background golden-set evaluation against a company's documents.

Uses the same retrieval, prompt and model as chat, but never persists
conversations and never touches the answer cache: evaluation runs must not
pollute failed questions, ratings or visitor traffic counters.
"""

import json
import time
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Company
from app.db.session import get_session_factory
from app.eval.golden import GoldenCase, load_golden
from app.eval.scoring import CaseResult, score_case, summarize
from app.providers.embeddings import get_embedding_provider
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.kv import get_kv_store
from app.providers.kv.base import KVStore
from app.providers.llm import get_llm_provider
from app.providers.llm.base import ChatMessage, LLMProvider
from app.providers.reranker import get_rerank_provider
from app.providers.reranker.base import RerankProvider
from app.rag.injection import leaks_prompt
from app.rag.language import detect_language
from app.rag.retrieval import retrieve
from app.schemas.chat import Citation
from app.services.rag_chat import (
    NOT_COVERED_ANSWER,
    OFF_TOPIC_ANSWER,
    _retry_instruction,
    build_context,
    build_system_prompt,
    is_no_answer,
    parse_citations,
    pre_llm_refusal,
    strong_hits,
)

log = structlog.get_logger()

EVAL_TTL_SECONDS = 24 * 3600
# A run left "running" by a crashed process must not block new runs forever.
STALE_RUN_SECONDS = 30 * 60


def _key(company_id: uuid.UUID) -> str:
    return f"eval:{company_id}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def get_eval_state(kv: KVStore, company_id: uuid.UUID) -> dict | None:
    raw = await kv.get(_key(company_id))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


async def start_eval(kv: KVStore, company_id: uuid.UUID) -> bool:
    """Claim the run slot. False when a fresh run is already in progress."""
    state = await get_eval_state(kv, company_id)
    if state is not None and state.get("status") == "running":
        started = state.get("started_at", "")
        try:
            age = (datetime.now(UTC) - datetime.fromisoformat(started)).total_seconds()
        except ValueError:
            age = STALE_RUN_SECONDS + 1
        if age < STALE_RUN_SECONDS:
            return False
    await kv.set(
        _key(company_id),
        json.dumps(
            {
                "status": "running",
                "started_at": _now(),
                "total": len(load_golden().cases),
                "completed": 0,
                "results": [],
            }
        ),
        ttl_seconds=EVAL_TTL_SECONDS,
    )
    return True


async def _publish(
    kv: KVStore,
    company_id: uuid.UUID,
    status: str,
    started_at: str,
    results: list[CaseResult],
    error: str | None = None,
) -> None:
    state = {
        "status": status,
        "started_at": started_at,
        "total": len(load_golden().cases),
        "completed": len(results),
        "results": [result.model_dump(mode="json") for result in results],
        "summary": summarize(results),
    }
    if status in ("done", "failed"):
        state["finished_at"] = _now()
    if error is not None:
        state["error"] = error
    await kv.set(_key(company_id), json.dumps(state), ttl_seconds=EVAL_TTL_SECONDS)


async def _answer_case(
    session: AsyncSession,
    company: Company,
    case: GoldenCase,
    embedder: EmbeddingProvider,
    llm: LLMProvider,
    settings: Settings,
    reranker: RerankProvider | None,
) -> tuple[str, list[Citation], str | None]:
    hits = await retrieve(
        session,
        company.id,
        case.question,
        embedder,
        settings,
        reranker,
        min_score=settings.retrieval_off_topic_score,
    )
    refusal = pre_llm_refusal(hits, case.question, case.language, settings)
    if refusal is not None:
        answer, kind = refusal
        return answer, [], kind
    hits = strong_hits(hits, settings)
    messages = [
        ChatMessage(role="system", content=build_system_prompt(case.language, build_context(hits))),
        ChatMessage(role="user", content=case.question),
    ]
    answer = await llm.chat(messages)
    if answer.strip() and detect_language(answer) != case.language:
        messages += [
            ChatMessage(role="assistant", content=answer),
            ChatMessage(role="user", content=_retry_instruction(case.language)),
        ]
        answer = await llm.chat(messages)
    if leaks_prompt(answer):
        return OFF_TOPIC_ANSWER[case.language], [], "off_topic"
    if is_no_answer(answer, case.language):
        return NOT_COVERED_ANSWER[case.language], [], "not_covered"
    return answer, parse_citations(answer, hits), None


async def run_evaluation(company_id: uuid.UUID) -> None:
    settings = get_settings()
    kv = get_kv_store()
    state = await get_eval_state(kv, company_id)
    started_at = (state or {}).get("started_at", _now())
    results: list[CaseResult] = []
    try:
        async with get_session_factory()() as session:
            company = await session.get(Company, company_id)
            if company is None:
                await _publish(kv, company_id, "failed", started_at, [], "Company not found.")
                return
            embedder = get_embedding_provider()
            llm = get_llm_provider()
            reranker = get_rerank_provider()
            for case in load_golden().cases:
                started = time.perf_counter()
                answer, citations, kind = await _answer_case(
                    session, company, case, embedder, llm, settings, reranker
                )
                duration_ms = round((time.perf_counter() - started) * 1000, 1)
                results.append(score_case(case, answer, citations, duration_ms, kind))
                await _publish(kv, company_id, "running", started_at, results)
        await _publish(kv, company_id, "done", started_at, results)
        summary = summarize(results)
        log.info(
            "eval_done",
            company_id=str(company_id),
            passed=summary["passed"],
            total=summary["total"],
        )
    except Exception as exc:
        log.exception("eval_failed", company_id=str(company_id))
        await _publish(kv, company_id, "failed", started_at, results, str(exc))