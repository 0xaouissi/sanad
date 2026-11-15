"""Live acceptance tests: real Ollama, real model, three languages.

Run with: pytest -m e2e
Requires Ollama running at OLLAMA_BASE_URL with the tier model pulled.
"""

import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from app.providers.llm import get_llm_provider
from app.providers.llm.base import LLMError
from app.providers.llm.ollama import OllamaProvider

pytestmark = pytest.mark.e2e

CASES = [
    ("ar", "ما هي عاصمة فرنسا؟", "باريس"),
    ("fr", "Quelle est la capitale de la France ?", "Paris"),
    ("en", "What is the capital of France?", "Paris"),
]


@pytest.fixture
async def live_client() -> AsyncIterator[AsyncClient]:
    provider = OllamaProvider(Settings())
    try:
        await provider.health()
    except LLMError as exc:
        pytest.skip(f"Live Ollama unavailable: {exc}")
    finally:
        await provider.aclose()
    # Each test runs in its own event loop; the cached provider's httpx client
    # must be rebuilt so it is not bound to a previous (closed) loop.
    get_llm_provider.cache_clear()
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as test_client:
        yield test_client
    get_llm_provider.cache_clear()


@pytest.mark.parametrize(("lang", "question", "expected"), CASES)
async def test_chat_answers_in_visitor_language(
    live_client: AsyncClient, lang: str, question: str, expected: str
) -> None:
    response = await live_client.post("/api/v1/chat", json={"message": question})
    assert response.status_code == 200, response.text
    answer = response.json()["answer"]
    assert expected.lower() in answer.lower()
    if lang == "ar":
        assert any("؀" <= ch <= "ۿ" for ch in answer)


async def test_chat_streams_tokens(live_client: AsyncClient) -> None:
    response = await live_client.post(
        "/api/v1/chat", json={"message": "Dis bonjour en un mot.", "stream": True}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert any(e["type"] == "token" and e["content"] for e in events)
    assert events[-1]["type"] == "done"