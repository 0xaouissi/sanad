import json

from httpx import AsyncClient

from tests.conftest import FakeProvider


def _events(text: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


async def test_chat_returns_answer(client: AsyncClient, fake_provider: FakeProvider) -> None:
    response = await client.post("/api/v1/chat", json={"message": "Bonjour"})
    assert response.status_code == 200
    assert response.json() == {
        "answer": fake_provider.answer,
        "model": "fake-model",
        "provider": "fake",
    }


async def test_chat_streams_sse(client: AsyncClient) -> None:
    response = await client.post("/api/v1/chat", json={"message": "Hi", "stream": True})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    assert events[-1] == {"type": "done"}
    answer = "".join(e["content"] for e in events if e["type"] == "token")
    assert answer.strip() == "Hello!"


async def test_chat_rejects_blank_message(client: AsyncClient) -> None:
    response = await client.post("/api/v1/chat", json={"message": "   "})
    assert response.status_code == 422


async def test_chat_provider_down_returns_503_with_hint(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    fake_provider.fail = True
    response = await client.post("/api/v1/chat", json={"message": "Hi"})
    assert response.status_code == 503
    assert "down" in response.json()["detail"]


async def test_chat_stream_reports_error_event(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    fake_provider.fail = True
    response = await client.post("/api/v1/chat", json={"message": "Hi", "stream": True})
    assert response.status_code == 200
    events = _events(response.text)
    assert events[-1]["type"] == "error"
    assert "down" in events[-1]["detail"]