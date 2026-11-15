from functools import lru_cache

from app.core.config import LLMProvider as LLMProviderKind
from app.core.config import get_settings
from app.providers.llm.base import LLMProvider
from app.providers.llm.ollama import OllamaProvider
from app.providers.llm.openai import OpenAIProvider

__all__ = ["LLMProvider", "OllamaProvider", "OpenAIProvider", "get_llm_provider"]


@lru_cache
def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    if settings.llm_provider is LLMProviderKind.OLLAMA:
        return OllamaProvider(settings)
    return OpenAIProvider(settings)