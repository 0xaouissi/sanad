import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.providers.llm import get_llm_provider
from app.providers.llm.base import (
    ChatMessage,
    LLMError,
    LLMProvider,
    LLMUnavailableError,
)
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])

SYSTEM_PROMPT = (
    "You are Sanad, a helpful assistant. Reply in the same language as the user's "
    "message (Modern Standard Arabic, French or English). Keep answers short and friendly."
)


def _messages(message: str) -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content=SYSTEM_PROMPT),
        ChatMessage(role="user", content=message),
    ]


async def _sse(
    provider: LLMProvider, messages: list[ChatMessage]
) -> AsyncIterator[str]:
    try:
        async for token in provider.stream_chat(messages):
            event = {"type": "token", "content": token}
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
    except LLMError as exc:
        event = {"type": "error", "detail": str(exc)}
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> ChatResponse | StreamingResponse:
    messages = _messages(request.message)
    if request.stream:
        return StreamingResponse(
            _sse(provider, messages), media_type="text/event-stream"
        )
    try:
        answer = await provider.chat(messages)
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ChatResponse(answer=answer, model=provider.model, provider=provider.name)