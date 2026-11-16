from functools import lru_cache

from app.core.config import get_settings
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.embeddings.bge_m3 import BgeM3Provider


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    return BgeM3Provider(get_settings())