import json
from collections.abc import AsyncIterator

import httpx

from app.core.config import Settings
from app.providers.llm.base import (
    ChatMessage,
    LLMError,
    LLMProvider,
    LLMUnavailableError,
)


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self.model = settings.resolved_llm_model
        self._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=settings.llm_timeout,
            transport=transport,
            # Ambient proxy entries (e.g. Windows NO_PROXY) must not affect local calls.
            trust_env=False,
        )

    def _payload(self, messages: list[ChatMessage], stream: bool) -> dict:
        options: dict = {
            "num_ctx": self._settings.resolved_num_ctx,
            "temperature": self._settings.llm_temperature,
        }
        num_gpu = self._settings.resolved_ollama_num_gpu
        if num_gpu is not None:
            options["num_gpu"] = num_gpu
        return {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "stream": stream,
            "options": options,
            "keep_alive": self._settings.ollama_keep_alive,
        }

    def _unreachable(self) -> LLMUnavailableError:
        return LLMUnavailableError(
            f"Ollama is not reachable at {self._settings.ollama_base_url}. "
            "Start it with `ollama serve`, or fix OLLAMA_BASE_URL."
        )

    def _model_missing(self) -> LLMUnavailableError:
        return LLMUnavailableError(
            f"Model '{self.model}' is not available in Ollama. "
            f"Run: ollama pull {self.model}"
        )

    def _timeout(self) -> LLMUnavailableError:
        return LLMUnavailableError(
            f"Ollama timed out after {self._settings.llm_timeout}s. The model may still "
            "be loading, or the machine is too weak for this tier: try MODEL_TIER=small "
            "or raise LLM_TIMEOUT."
        )

    async def chat(self, messages: list[ChatMessage]) -> str:
        try:
            response = await self._client.post(
                "/api/chat", json=self._payload(messages, stream=False)
            )
        except httpx.ConnectError as exc:
            raise self._unreachable() from exc
        except httpx.TimeoutException as exc:
            raise self._timeout() from exc
        if response.status_code == 404:
            raise self._model_missing()
        if response.status_code != 200:
            raise LLMError(f"Ollama returned {response.status_code}: {response.text}")
        return response.json()["message"]["content"]

    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        try:
            async with self._client.stream(
                "POST", "/api/chat", json=self._payload(messages, stream=True)
            ) as response:
                if response.status_code == 404:
                    raise self._model_missing()
                if response.status_code != 200:
                    await response.aread()
                    raise LLMError(f"Ollama returned {response.status_code}: {response.text}")
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise LLMError(f"Ollama stream error: {chunk['error']}")
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break
        except httpx.ConnectError as exc:
            raise self._unreachable() from exc
        except httpx.TimeoutException as exc:
            raise self._timeout() from exc

    async def health(self) -> None:
        try:
            response = await self._client.get("/api/tags")
        except httpx.ConnectError as exc:
            raise self._unreachable() from exc
        except httpx.TimeoutException as exc:
            raise self._timeout() from exc
        if response.status_code != 200:
            raise LLMError(f"Ollama returned {response.status_code}: {response.text}")
        names = [m.get("name") for m in response.json().get("models", [])]
        if self.model not in names:
            raise self._model_missing()

    async def aclose(self) -> None:
        await self._client.aclose()