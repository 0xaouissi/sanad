import json
from collections.abc import Callable

import httpx
import pytest
from pytest import MonkeyPatch

from app.core.config import Settings, get_settings
from app.providers.llm import get_llm_provider
from app.providers.llm.base import ChatMessage, LLMUnavailableError
from app.providers.llm.ollama import OllamaProvider
from app.providers.llm.openai import OpenAIProvider

MESSAGES = [ChatMessage(role="user", content="hi")]
Handler = Callable[[httpx.Request], httpx.Response]


def ollama(handler: Handler, **overrides) -> OllamaProvider:
    return OllamaProvider(Settings(**overrides), transport=httpx.MockTransport(handler))


def openai_provider(handler: Handler, **overrides) -> OpenAIProvider:
    settings = Settings(llm_provider="openai", openai_api_key="sk-test", **overrides)
    return OpenAIProvider(settings, transport=httpx.MockTransport(handler))


async def test_ollama_chat_returns_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "مرحبا"}})

    assert await ollama(handler).chat(MESSAGES) == "مرحبا"


async def test_ollama_payload_follows_tier_settings() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "ok"}})

    await ollama(handler, model_tier="medium").chat(MESSAGES)
    assert captured["model"] == "qwen2.5:7b-instruct-q4_K_M"
    assert captured["options"]["num_ctx"] == 16384
    assert captured["options"]["temperature"] == 0.0
    assert captured["keep_alive"] == "5m"
    assert "num_gpu" not in captured["options"]


async def test_ollama_cpu_only_sends_num_gpu_zero() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "ok"}})

    await ollama(handler, cpu_only=True).chat(MESSAGES)
    assert captured["options"]["num_gpu"] == 0


async def test_ollama_stream_yields_deltas() -> None:
    body = '{"message":{"content":"a"}}\n{"message":{"content":"b"},"done":true}\n'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    tokens = [token async for token in ollama(handler).stream_chat(MESSAGES)]
    assert tokens == ["a", "b"]


async def test_ollama_missing_model_gives_pull_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found"})

    with pytest.raises(LLMUnavailableError, match="ollama pull"):
        await ollama(handler).chat(MESSAGES)


async def test_ollama_unreachable_gives_start_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(LLMUnavailableError, match="ollama serve"):
        await ollama(handler).chat(MESSAGES)


async def test_ollama_health_requires_model_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"models": [{"name": "qwen2.5:3b-instruct-q4_K_M"}]}
        )

    await ollama(handler).health()

    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": []})

    with pytest.raises(LLMUnavailableError, match="ollama pull"):
        await ollama(empty).health()


async def test_openai_chat_sends_auth_and_parses_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-test"
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "Bonjour"}}]}
        )

    assert await openai_provider(handler).chat(MESSAGES) == "Bonjour"


async def test_openai_stream_parses_sse() -> None:
    body = (
        'data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"b"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    tokens = [token async for token in openai_provider(handler).stream_chat(MESSAGES)]
    assert tokens == ["a", "b"]


async def test_openai_bad_key_gives_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(LLMUnavailableError, match="OPENAI_API_KEY"):
        await openai_provider(handler).chat(MESSAGES)


def test_factory_selects_provider_from_config(monkeypatch: MonkeyPatch) -> None:
    get_settings.cache_clear()
    get_llm_provider.cache_clear()
    try:
        assert isinstance(get_llm_provider(), OllamaProvider)
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        get_settings.cache_clear()
        get_llm_provider.cache_clear()
        assert isinstance(get_llm_provider(), OpenAIProvider)
    finally:
        get_settings.cache_clear()
        get_llm_provider.cache_clear()


async def test_ollama_think_omitted_by_default() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "ok"}})

    await ollama(handler).chat(MESSAGES)
    assert "think" not in captured


async def test_ollama_think_sent_when_configured() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "ok"}})

    await ollama(handler, llm_think=False).chat(MESSAGES)
    assert captured["think"] is False