from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy import delete, func, select

from app.api.deps import CsrfDep, DashboardAuthDep, OwnerDep, SessionDep
from app.api.v1.documents import (
    delete_document,
    list_documents,
    reindex_document,
    upload_document,
)
from app.core.passwords import hash_password
from app.core.security import generate_api_key, generate_site_key, hash_api_key
from app.db.models import (
    Conversation,
    DashboardUser,
    Document,
    DocumentStatus,
    Feedback,
    Message,
    UserRole,
)
from app.eval.golden import golden_summary
from app.providers.kv import get_kv_store
from app.schemas.auth import UserCreate, UserResponse
from app.schemas.dashboard import (
    DashboardSettings,
    DeletedCount,
    FailedQuestion,
    KeyRotation,
    RatingOut,
    RatingsSummary,
    SettingsUpdate,
)
from app.schemas.document import DocumentAccepted, DocumentOut
from app.services.evaluation import get_eval_state, run_evaluation, start_eval
from app.services.rag_chat import is_no_answer

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/users", response_model=list[UserResponse])
async def list_users(auth: OwnerDep, session: SessionDep) -> list[UserResponse]:
    users = await session.scalars(
        select(DashboardUser)
        .where(DashboardUser.company_id == auth.company.id)
        .order_by(DashboardUser.created_at)
    )
    return [
        UserResponse(id=u.id, email=u.email, role=u.role, created_at=u.created_at) for u in users
    ]


@router.post("/users", response_model=UserResponse, status_code=201)
async def add_viewer(
    body: UserCreate, auth: OwnerDep, session: SessionDep, _: CsrfDep
) -> UserResponse:
    existing = await session.scalar(select(DashboardUser).where(DashboardUser.email == body.email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="This email already has an account.")
    user = DashboardUser(
        company_id=auth.company.id,
        email=body.email,
        password_hash=hash_password(body.password),
        role=UserRole.VIEWER,
    )
    session.add(user)
    await session.commit()
    return UserResponse(id=user.id, email=user.email, role=user.role, created_at=user.created_at)


# Documents: same behavior as the secret-key API, authenticated by the
# dashboard session. Mutations are owner-only; viewers can list.


@router.get("/documents", response_model=list[DocumentOut])
async def dashboard_documents(auth: DashboardAuthDep, session: SessionDep) -> list[Document]:
    return await list_documents(auth.company, session)


@router.post("/documents", response_model=DocumentAccepted, status_code=202)
async def dashboard_upload(
    auth: OwnerDep,
    session: SessionDep,
    background: BackgroundTasks,
    file: UploadFile,
    _: CsrfDep,
) -> DocumentAccepted:
    return await upload_document(auth.company, session, background, file)


@router.delete("/documents/{document_id}", status_code=204)
async def dashboard_delete_document(
    auth: OwnerDep, session: SessionDep, document_id: UUID, _: CsrfDep
) -> None:
    await delete_document(auth.company, session, document_id)


@router.post("/documents/{document_id}/reindex", response_model=DocumentAccepted, status_code=202)
async def dashboard_reindex(
    auth: OwnerDep,
    session: SessionDep,
    background: BackgroundTasks,
    document_id: UUID,
    _: CsrfDep,
) -> DocumentAccepted:
    return await reindex_document(auth.company, session, background, document_id)


async def _recent_messages(session: SessionDep, company_id: UUID, limit: int = 1000):
    """Latest messages across the company's conversations, oldest first."""
    rows = (
        await session.execute(
            select(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(Conversation.company_id == company_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(reversed(rows))


def _question_for(messages: list[Message], assistant: Message) -> str | None:
    # Timestamps can tie within one turn (Windows clock resolution), so match
    # by conversation and <= created_at rather than list position.
    candidates = [
        m
        for m in messages
        if m.role == "user"
        and m.conversation_id == assistant.conversation_id
        and m.created_at <= assistant.created_at
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda m: m.created_at).content


@router.get("/failed-questions", response_model=list[FailedQuestion])
async def failed_questions(auth: DashboardAuthDep, session: SessionDep) -> list[FailedQuestion]:
    messages = await _recent_messages(session, auth.company.id)
    failed = []
    for message in messages:
        if message.role != "assistant" or not message.language:
            continue
        if not is_no_answer(message.content, message.language):
            continue
        failed.append(
            FailedQuestion(
                message_id=message.id,
                conversation_id=message.conversation_id,
                question=_question_for(messages, message) or "",
                language=message.language,
                created_at=message.created_at,
            )
        )
    return list(reversed(failed))[:100]


@router.get("/ratings", response_model=RatingsSummary)
async def ratings(auth: DashboardAuthDep, session: SessionDep) -> RatingsSummary:
    rows = (
        await session.execute(
            select(Feedback, Message)
            .join(Message, Feedback.message_id == Message.id)
            .where(Feedback.company_id == auth.company.id)
            .order_by(Feedback.created_at.desc())
            .limit(200)
        )
    ).all()
    messages = await _recent_messages(session, auth.company.id)
    items = []
    up = down = 0
    for feedback, message in rows:
        if feedback.rating == "up":
            up += 1
        else:
            down += 1
        items.append(
            RatingOut(
                message_id=message.id,
                rating=feedback.rating,
                question=_question_for(messages, message),
                answer=message.content[:300],
                language=message.language,
                created_at=feedback.created_at,
            )
        )
    return RatingsSummary(up=up, down=down, items=items)


def _settings_payload(company) -> DashboardSettings:
    return DashboardSettings(
        company_name=company.name,
        site_key=company.site_key,
        allowed_domains=company.allowed_domains,
        store_conversations=company.store_conversations,
    )


@router.get("/settings", response_model=DashboardSettings)
async def get_settings_endpoint(auth: DashboardAuthDep) -> DashboardSettings:
    return _settings_payload(auth.company)


@router.put("/settings", response_model=DashboardSettings)
async def update_settings(
    body: SettingsUpdate, auth: OwnerDep, session: SessionDep, _: CsrfDep
) -> DashboardSettings:
    if body.allowed_domains is not None:
        auth.company.allowed_domains = body.allowed_domains
    if body.store_conversations is not None:
        auth.company.store_conversations = body.store_conversations
    await session.commit()
    return _settings_payload(auth.company)


@router.post("/keys/rotate", response_model=KeyRotation)
async def rotate_keys(auth: OwnerDep, session: SessionDep, _: CsrfDep) -> KeyRotation:
    api_key = generate_api_key()
    auth.company.api_key_hash = hash_api_key(api_key)
    auth.company.site_key = generate_site_key()
    await session.commit()
    return KeyRotation(api_key=api_key, site_key=auth.company.site_key)


@router.get("/export")
async def export_data(auth: OwnerDep, session: SessionDep) -> JSONResponse:
    company = auth.company
    documents = (
        await session.scalars(select(Document).where(Document.company_id == company.id))
    ).all()
    conversations = (
        await session.scalars(
            select(Conversation)
            .where(Conversation.company_id == company.id)
            .order_by(Conversation.created_at)
        )
    ).all()
    messages = (
        await session.scalars(
            select(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(Conversation.company_id == company.id)
            .order_by(Message.created_at)
        )
    ).all()
    feedback = (
        await session.scalars(select(Feedback).where(Feedback.company_id == company.id))
    ).all()
    by_conversation: dict[UUID, list] = {}
    for message in messages:
        by_conversation.setdefault(message.conversation_id, []).append(
            {
                "id": str(message.id),
                "role": message.role,
                "content": message.content,
                "language": message.language,
                "created_at": message.created_at.isoformat(),
            }
        )
    payload = {
        "company": {
            "id": str(company.id),
            "name": company.name,
            "allowed_domains": company.allowed_domains,
            "store_conversations": company.store_conversations,
            "created_at": company.created_at.isoformat(),
        },
        "documents": [
            {
                "id": str(d.id),
                "filename": d.filename,
                "status": d.status,
                "chunk_count": d.chunk_count,
                "created_at": d.created_at.isoformat(),
            }
            for d in documents
        ],
        "conversations": [
            {
                "id": str(c.id),
                "created_at": c.created_at.isoformat(),
                "messages": by_conversation.get(c.id, []),
            }
            for c in conversations
        ],
        "feedback": [
            {
                "message_id": str(f.message_id),
                "rating": f.rating,
                "created_at": f.created_at.isoformat(),
            }
            for f in feedback
        ],
    }
    return JSONResponse(
        payload,
        headers={"Content-Disposition": 'attachment; filename="sanad-export.json"'},
    )


@router.delete("/conversations", response_model=DeletedCount)
async def delete_all_conversations(
    auth: OwnerDep, session: SessionDep, _: CsrfDep
) -> DeletedCount:
    count = await session.scalar(
        select(func.count())
        .select_from(Conversation)
        .where(Conversation.company_id == auth.company.id)
    )
    await session.execute(delete(Conversation).where(Conversation.company_id == auth.company.id))
    await session.commit()
    return DeletedCount(deleted=count or 0)


# Evaluation (Step 6a): run the golden set against this company's documents.


@router.post("/eval/run", status_code=202)
async def run_eval(
    auth: OwnerDep, background: BackgroundTasks, _: CsrfDep
) -> dict:
    kv = get_kv_store()
    try:
        claimed = await start_eval(kv, auth.company.id)
    except (RedisError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Evaluation state unavailable ({exc}). Check REDIS_URL or restart the app.",
        ) from exc
    if not claimed:
        raise HTTPException(
            status_code=409, detail="An evaluation is already running. Wait for it to finish."
        )
    background.add_task(run_evaluation, auth.company.id)
    return {"status": "running"}


@router.get("/eval")
async def eval_state(auth: DashboardAuthDep, session: SessionDep) -> dict:
    try:
        state = await get_eval_state(get_kv_store(), auth.company.id)
    except (RedisError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Evaluation state unavailable ({exc}). Check REDIS_URL or restart the app.",
        ) from exc
    state = dict(state) if state else {"status": "idle"}
    state["golden"] = golden_summary()
    ready = set(
        (
            await session.scalars(
                select(Document.filename).where(
                    Document.company_id == auth.company.id,
                    Document.status == DocumentStatus.READY,
                )
            )
        ).all()
    )
    state["documents_ready"] = all(name in ready for name in golden_summary()["documents"])
    return state