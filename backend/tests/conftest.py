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
    "LLM_TEMPERATURE",
    "OLLAMA_BASE_URL",
    "OLLAMA_NUM_GPU",
    "OLLAMA_KEEP_ALIVE",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_BASE_URL",
    "EMBEDDING_MODEL",
    "EMBEDDING_DEVICE",
    "EMBEDDING_BATCH_SIZE",
    "HF_HOME",
    "ADMIN_API_KEY",
    "DATA_DIR",
    "MAX_UPLOAD_MB",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "TESSERACT_CMD",
    "TESSDATA_PREFIX",
    "OCR_LANGUAGES",
    "RERANK_ENABLED",
    "RERANK_MODEL",
    "RERANK_CANDIDATES",
    "RETRIEVAL_TOP_K",
    "RETRIEVAL_MIN_SCORE",
    "MEMORY_MAX_TURNS",
    "CACHE_ENABLED",
    "CACHE_TTL_SECONDS",
    "RATE_LIMIT_PER_IP",
    "RATE_LIMIT_PER_SITE",
    "DAILY_CAP_PER_COMPANY",
    "TRUST_FORWARDED_FOR",
    "BOT_CHECK_ENABLED",
    "BOT_CHECK_MIN_SECONDS",
    "DASHBOARD_SESSION_HOURS",
    "LOGIN_RATE_LIMIT_PER_MINUTE",
    "COOKIE_SECURE",
    "CRAWL_MAX_PAGES",
    "CRAWL_MAX_PAGE_BYTES",
    "CRAWL_TIMEOUT_SECONDS",
    "CRAWL_MAX_SECONDS",
    "CRAWL_RESYNC_HOURS",
    "CRAWL_ALLOW_PRIVATE",
    "CRAWL_USER_AGENT",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: MonkeyPatch, tmp_path) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    # Run from an empty cwd so the developer's backend/.env never leaks into tests.
    monkeypatch.chdir(tmp_path)


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