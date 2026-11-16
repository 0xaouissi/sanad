from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import ChatCompanyDep, SessionDep
from app.db.models import Conversation, Feedback, Message
from app.schemas.feedback import FeedbackRequest, FeedbackResponse

router = APIRouter(tags=["feedback"])


@router.post("/feedback", response_model=FeedbackResponse, status_code=201)
async def create_feedback(
    body: FeedbackRequest, company: ChatCompanyDep, session: SessionDep
) -> FeedbackResponse:
    message = await session.scalar(
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Message.id == body.message_id, Conversation.company_id == company.id)
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found for this company.")
    if message.role != "assistant":
        raise HTTPException(status_code=422, detail="Only assistant messages can be rated.")
    existing = await session.scalar(
        select(Feedback).where(Feedback.message_id == body.message_id)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="This message already has a rating.")
    feedback = Feedback(
        company_id=company.id, message_id=body.message_id, rating=body.rating
    )
    session.add(feedback)
    await session.commit()
    return FeedbackResponse(
        id=feedback.id, message_id=feedback.message_id, rating=feedback.rating
    )