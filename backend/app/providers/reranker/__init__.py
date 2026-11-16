from functools import lru_cache

from app.core.config import get_settings
from app.providers.reranker.base import RerankProvider
from app.providers.reranker.bge import BgeRerankerProvider


@lru_cache
def get_rerank_provider() -> RerankProvider | None:
    settings = get_settings()
    if not settings.resolved_rerank_enabled:
        return None
    return BgeRerankerProvider(settings)