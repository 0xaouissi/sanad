import uuid
from typing import Literal

from pydantic import BaseModel


class FeedbackRequest(BaseModel):
    message_id: uuid.UUID
    rating: Literal["up", "down"]


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    rating: str