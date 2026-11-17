import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ChatCompanyDep, KVDep, SessionDep
from app.core.config import get_settings
from app.db.models import Company
from app.providers.embeddings import get_embedding_provider
from app.providers.embeddings.base import EmbeddingError, EmbeddingProvider
from app.providers.llm import get_llm_provider
from app.providers.llm.base import LLMError, LLMProvider, LLMUnavailableError
from app.providers.reranker import get_rerank_provider
from app.providers.reranker.base import RerankError, RerankProvider
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.bot_check import enforce_bot_check
from app.services.rag_chat import ConversationNotFoundError, answer_question, stream_answer
from app.services.rate_limit import enforce_chat_limits

router = APIRouter(tags=["chat"])

EmbedderDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]
RerankerDep = Annotated[RerankProvider | None, Depends(get_rerank_provider)]
LLMDep = Annotated[LLMProvider, Depends(get_llm_provider)]


async def _sse(
    session: AsyncSession, company: Company, question: str, **kwargs
) -> AsyncIterator[str]:
    try:
        async for event in stream_answer(session, company, question, **kwargs):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    except (ConversationNotFoundError, LLMError, EmbeddingError, RerankError) as exc:
        event = {"type": "error", "detail": str(exc)}
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    raw_request: Request,
    company: ChatCompanyDep,
    session: SessionDep,
    embedder: EmbedderDep,
    reranker: RerankerDep,
    llm: LLMDep,
    kv: KVDep,
) -> ChatResponse | StreamingResponse:
    settings = get_settings()
    # Mirrors get_chat_company: the secret key wins when both are present.
    via_site_key = "x-site-key" in raw_request.headers and "x-api-key" not in raw_request.headers
    enforce_bot_check(request, via_site_key, settings)
    await enforce_chat_limits(kv, raw_request, company.id, settings)
    kwargs = {
        "embedder": embedder,
        "llm": llm,
        "settings": settings,
        "reranker": reranker,
        "conversation_id": request.conversation_id,
        "language": request.language,
        "kv": kv,
    }
    if request.stream:
        return StreamingResponse(
            _sse(session, company, request.message, **kwargs),
            media_type="text/event-stream",
        )
    try:
        outcome = await answer_question(session, company, request.message, **kwargs)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (EmbeddingError, RerankError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ChatResponse(
        answer=outcome.answer,
        model=llm.model,
        provider=llm.name,
        language=outcome.language,
        conversation_id=outcome.conversation_id,
        message_id=outcome.message_id,
        citations=outcome.citations,
        refusal_kind=outcome.refusal_kind,
    )