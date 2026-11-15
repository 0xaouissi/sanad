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


class OpenAIProvider(LLMProvider):
    """Any OpenAI-compatible chat completions API, selected purely by configuration."""

    name = "openai"

    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self.model = settings.openai_model
        self._client = httpx.AsyncClient(
            base_url=settings.openai_base_url,
            timeout=settings.llm_timeout,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            transport=transport,
            trust_env=False,
        )

    def _payload(self, messages: list[ChatMessage], stream: bool) -> dict:
        return {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "stream": stream,
        }

    def _check_status(self, response: httpx.Response) -> None:
        if response.status_code == 401:
            raise LLMUnavailableError("API key rejected. Check OPENAI_API_KEY.")
        if response.status_code == 404:
            raise LLMUnavailableError(
                f"Model '{self.model}' not found by the API. Check OPENAI_MODEL."
            )
        if response.status_code != 200:
            raise LLMError(f"API returned {response.status_code}: {response.text}")

    async def chat(self, messages: list[ChatMessage]) -> str:
        try:
            response = await self._client.post(
                "/chat/completions", json=self._payload(messages, stream=False)
            )
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(
                f"API is not reachable at {self._settings.openai_base_url}. "
                "Check OPENAI_BASE_URL and your network connection."
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMUnavailableError(
                f"API timed out after {self._settings.llm_timeout}s. Raise LLM_TIMEOUT."
            ) from exc
        self._check_status(response)
        return response.json()["choices"][0]["message"]["content"]

    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        try:
            async with self._client.stream(
                "POST", "/chat/completions", json=self._payload(messages, stream=True)
            ) as response:
                if response.status_code != 200:
                    await response.aread()
                    self._check_status(response)
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line.removeprefix("data: ").strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {}).get("content")
                    if delta:
                        yield delta
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(
                f"API is not reachable at {self._settings.openai_base_url}. "
                "Check OPENAI_BASE_URL and your network connection."
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMUnavailableError(
                f"API timed out after {self._settings.llm_timeout}s. Raise LLM_TIMEOUT."
            ) from exc

    async def health(self) -> None:
        try:
            response = await self._client.get("/models")
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(
                f"API is not reachable at {self._settings.openai_base_url}. "
                "Check OPENAI_BASE_URL and your network connection."
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMUnavailableError(
                f"API timed out after {self._settings.llm_timeout}s. Raise LLM_TIMEOUT."
            ) from exc
        self._check_status(response)

    async def aclose(self) -> None:
        await self._client.aclose()