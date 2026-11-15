from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Literal

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMError(Exception):
    """Base class for provider failures."""


class LLMUnavailableError(LLMError):
    """Service unreachable or model missing. The message tells the user how to fix it."""


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def chat(self, messages: list[ChatMessage]) -> str: ...

    @abstractmethod
    def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[str]: ...

    @abstractmethod
    async def health(self) -> None:
        """Raise LLMError with an actionable message when the provider is not usable."""

    async def aclose(self) -> None:
        return None