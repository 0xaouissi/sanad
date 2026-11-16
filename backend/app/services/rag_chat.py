"""Grounded chat: answers come only from the company's retrieved documents.

Below the relevance threshold the LLM is never called — the visitor gets a
localized "I don't know" with an offer to contact support. Wrong-language
answers are retried once with an explicit instruction.
"""

import re
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Company, Conversation, Message
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.llm.base import ChatMessage, LLMProvider
from app.providers.reranker.base import RerankProvider
from app.rag.language import detect_language
from app.rag.retrieval import RetrievalHit, retrieve
from app.schemas.chat import Citation

log = structlog.get_logger()

LANGUAGE_NAMES = {"ar": "Modern Standard Arabic", "fr": "French", "en": "English"}

NO_ANSWER = {
    "en": (
        "I don't know based on the documents available. "
        "Please contact our support team for assistance."
    ),
    "fr": (
        "Je ne sais pas d'après les documents disponibles. "
        "Veuillez contacter notre équipe d'assistance pour obtenir de l'aide."
    ),
    "ar": (
        "لا أعرف بناءً على الوثائق المتاحة. "
        "يرجى التواصل مع فريق الدعم للحصول على المساعدة."
    ),
}

# How many characters of a streamed answer to buffer before judging its language.
LANGUAGE_CHECK_CHARS = 120

_CITATION_RE = re.compile(r"\[(\d+)\]")


class ConversationNotFoundError(Exception):
    """conversation_id does not exist or belongs to another company."""


@dataclass(frozen=True)
class ChatOutcome:
    answer: str
    language: str
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    citations: list[Citation]


def build_context(hits: list[RetrievalHit]) -> str:
    blocks = []
    for index, hit in enumerate(hits, start=1):
        location = hit.filename
        if hit.page_number is not None:
            location += f", page {hit.page_number}"
        if hit.heading:
            location += f', section "{hit.heading}"'
        blocks.append(f"[{index}] ({location})\n{hit.content}")
    return "\n\n".join(blocks)


def build_system_prompt(language: str, context: str) -> str:
    name = LANGUAGE_NAMES[language]
    return (
        "You are Sanad, a customer-support assistant. Answer the user's question "
        "ONLY using the numbered sources below. Rules:\n"
        f"1. Write the entire answer in {name}, whatever language the question "
        "is written in. Answer the question; do not repeat or translate it.\n"
        "2. Use only facts stated in the sources. Never use outside knowledge.\n"
        "3. Cite the sources you use inline with their numbers, like [1] or [2].\n"
        "4. If the sources do not contain the answer, reply exactly: "
        f'"{NO_ANSWER[language]}"\n'
        "5. Keep the answer short and friendly.\n\n"
        f"Sources:\n{context}"
    )


def is_no_answer(answer: str, language: str) -> bool:
    # The model sometimes appends citation markers to the refusal template.
    return _CITATION_RE.sub("", answer).strip() == NO_ANSWER[language].strip()


def parse_citations(answer: str, hits: list[RetrievalHit]) -> list[Citation]:
    used = {int(n) for n in _CITATION_RE.findall(answer)}
    indexes = sorted(i for i in used if 1 <= i <= len(hits))
    if not indexes:
        indexes = list(range(1, len(hits) + 1))
    return [
        Citation(
            index=i,
            chunk_id=hits[i - 1].chunk_id,
            document_id=hits[i - 1].document_id,
            filename=hits[i - 1].filename,
            page_number=hits[i - 1].page_number,
            heading=hits[i - 1].heading,
        )
        for i in indexes
    ]


def _retry_instruction(language: str) -> str:
    name = LANGUAGE_NAMES[language]
    return (
        f"Your previous answer was not written in {name}. Answer the same question "
        f"again, entirely in {name}, using the same numbered sources and citation markers."
    )


async def _get_conversation(
    session: AsyncSession, company_id: uuid.UUID, conversation_id: uuid.UUID | None
) -> Conversation:
    if conversation_id is None:
        conversation = Conversation(company_id=company_id)
        session.add(conversation)
        await session.flush()
        return conversation
    conversation = await session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.company_id == company_id
        )
    )
    if conversation is None:
        raise ConversationNotFoundError(
            f"Conversation {conversation_id} not found for this company."
        )
    return conversation


async def _history(
    session: AsyncSession, conversation_id: uuid.UUID, max_messages: int
) -> list[ChatMessage]:
    if max_messages <= 0:
        return []
    rows = (
        (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(max_messages)
            )
        )
        .scalars()
        .all()
    )
    return [ChatMessage(role=m.role, content=m.content) for m in reversed(rows)]


async def _save_turn(
    session: AsyncSession,
    conversation: Conversation,
    question: str,
    answer: str,
    language: str,
) -> uuid.UUID:
    session.add(
        Message(conversation_id=conversation.id, role="user", content=question, language=language)
    )
    assistant = Message(
        conversation_id=conversation.id, role="assistant", content=answer, language=language
    )
    session.add(assistant)
    conversation.updated_at = datetime.now(UTC)
    await session.commit()
    return assistant.id


def _prepare_messages(
    language: str, hits: list[RetrievalHit], history: list[ChatMessage], question: str
) -> list[ChatMessage]:
    system = build_system_prompt(language, build_context(hits))
    return (
        [ChatMessage(role="system", content=system)]
        + history
        + [ChatMessage(role="user", content=question)]
    )


def _retrieval_query(question: str, history: list[ChatMessage]) -> str:
    # Follow-ups like "Are you sure?" share no words with the documents;
    # the previous user turn carries the topic into retrieval.
    last_user = next((m.content for m in reversed(history) if m.role == "user"), None)
    return f"{last_user} {question}" if last_user else question


async def answer_question(
    session: AsyncSession,
    company: Company,
    question: str,
    *,
    embedder: EmbeddingProvider,
    llm: LLMProvider,
    settings: Settings,
    reranker: RerankProvider | None = None,
    conversation_id: uuid.UUID | None = None,
    language: str | None = None,
) -> ChatOutcome:
    started = time.perf_counter()
    language = language or detect_language(question)
    conversation = await _get_conversation(session, company.id, conversation_id)
    history = await _history(session, conversation.id, settings.memory_max_turns)

    retrieval_start = time.perf_counter()
    hits = await retrieve(
        session, company.id, _retrieval_query(question, history), embedder, settings, reranker
    )
    retrieval_ms = round((time.perf_counter() - retrieval_start) * 1000, 1)

    if not hits:
        answer = NO_ANSWER[language]
        citations: list[Citation] = []
        log.info(
            "chat_no_answer", language=language, retrieval_ms=retrieval_ms, tier=settings.model_tier
        )
    else:
        messages = _prepare_messages(language, hits, history, question)
        answer = await llm.chat(messages)
        if answer.strip() and detect_language(answer) != language:
            log.info("chat_language_retry", expected=language, detected=detect_language(answer))
            messages += [
                ChatMessage(role="assistant", content=answer),
                ChatMessage(role="user", content=_retry_instruction(language)),
            ]
            answer = await llm.chat(messages)
        if is_no_answer(answer, language):
            answer = NO_ANSWER[language]
            citations = []
        else:
            citations = parse_citations(answer, hits)
        log.info(
            "chat_latency",
            mode="sync",
            total_ms=round((time.perf_counter() - started) * 1000, 1),
            retrieval_ms=retrieval_ms,
            sources=len(hits),
            tier=settings.model_tier,
        )

    message_id = await _save_turn(session, conversation, question, answer, language)
    return ChatOutcome(
        answer=answer,
        language=language,
        conversation_id=conversation.id,
        message_id=message_id,
        citations=citations,
    )


async def _stream_with_retry(
    llm: LLMProvider, messages: list[ChatMessage], language: str
) -> AsyncIterator[str]:
    pending = ""
    decided = False
    retry = False
    async for token in llm.stream_chat(messages):
        if decided:
            yield token
            continue
        pending += token
        if len(pending) >= LANGUAGE_CHECK_CHARS:
            decided = True
            if detect_language(pending) != language:
                retry = True
                break
            yield pending
    if retry:
        log.info("chat_language_retry", expected=language, mode="stream")
        retry_messages = messages + [
            ChatMessage(role="assistant", content=pending),
            ChatMessage(role="user", content=_retry_instruction(language)),
        ]
        async for token in llm.stream_chat(retry_messages):
            yield token
        return
    if not decided:
        if pending.strip() and detect_language(pending) != language:
            log.info("chat_language_retry", expected=language, mode="stream_short")
            retry_messages = messages + [
                ChatMessage(role="assistant", content=pending),
                ChatMessage(role="user", content=_retry_instruction(language)),
            ]
            async for token in llm.stream_chat(retry_messages):
                yield token
        elif pending:
            yield pending


async def stream_answer(
    session: AsyncSession,
    company: Company,
    question: str,
    *,
    embedder: EmbeddingProvider,
    llm: LLMProvider,
    settings: Settings,
    reranker: RerankProvider | None = None,
    conversation_id: uuid.UUID | None = None,
    language: str | None = None,
) -> AsyncIterator[dict]:
    started = time.perf_counter()
    language = language or detect_language(question)
    conversation = await _get_conversation(session, company.id, conversation_id)
    history = await _history(session, conversation.id, settings.memory_max_turns)

    retrieval_start = time.perf_counter()
    hits = await retrieve(
        session, company.id, _retrieval_query(question, history), embedder, settings, reranker
    )
    retrieval_ms = round((time.perf_counter() - retrieval_start) * 1000, 1)

    if not hits:
        answer = NO_ANSWER[language]
        citations: list[Citation] = []
        yield {"type": "token", "content": answer}
        log.info(
            "chat_no_answer", language=language, retrieval_ms=retrieval_ms, tier=settings.model_tier
        )
    else:
        messages = _prepare_messages(language, hits, history, question)
        pieces: list[str] = []
        first_token_ms: float | None = None
        async for token in _stream_with_retry(llm, messages, language):
            if first_token_ms is None:
                first_token_ms = round((time.perf_counter() - started) * 1000, 1)
            pieces.append(token)
            yield {"type": "token", "content": token}
        answer = "".join(pieces)
        if is_no_answer(answer, language):
            answer = NO_ANSWER[language]
            citations = []
        else:
            citations = parse_citations(answer, hits)
        budget_ms = settings.first_token_budget_s * 1000
        log.info(
            "chat_latency",
            mode="stream",
            first_token_ms=first_token_ms,
            budget_ms=budget_ms,
            within_budget=first_token_ms is not None and first_token_ms <= budget_ms,
            retrieval_ms=retrieval_ms,
            sources=len(hits),
            tier=settings.model_tier,
        )

    message_id = await _save_turn(session, conversation, question, answer, language)
    yield {
        "type": "done",
        "conversation_id": str(conversation.id),
        "message_id": str(message_id),
        "language": language,
        "citations": [citation.model_dump(mode="json") for citation in citations],
    }