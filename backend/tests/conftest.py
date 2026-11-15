from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.main import create_app
from app.providers.llm import get_llm_provider
from app.providers.llm.base import ChatMessage, LLMProvider, LLMUnavailableError

ENV_KEYS = [
    "APP_NAME",
    "LOG_LEVEL",
    "LLM_TIMEOUT",
    "DATABASE_URL",
    "REDIS_URL",
    "MODEL_TIER",
    "CPU_ONLY",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_NUM_CTX",
    "OLLAMA_BASE_URL",
    "OLLAMA_NUM_GPU",
    "OLLAMA_KEEP_ALIVE",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_BASE_URL",
    "EMBEDDING_MODEL",
    "EMBEDDING_DEVICE",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: MonkeyPatch) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class FakeProvider(LLMProvider):
    name = "fake"
    model = "fake-model"

    def __init__(self, answer: str = "Hello!", fail: bool = False) -> None:
        self.answer = answer
        self.fail = fail

    def _check(self) -> None:
        if self.fail:
            raise LLMUnavailableError("model service is down (fake)")

    async def chat(self, messages: list[ChatMessage]) -> str:
        self._check()
        return self.answer

    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        self._check()
        for word in self.answer.split():
            yield word + " "

    async def health(self) -> None:
        self._check()


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
async def client(fake_provider: FakeProvider) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_llm_provider] = lambda: fake_provider
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as test_client:
        yield test_client