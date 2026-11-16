import asyncio
import math

import structlog

from app.core.config import Settings
from app.providers.reranker.base import RerankError, RerankProvider

log = structlog.get_logger()


def _sigmoid(x: float) -> float:
    if x <= -60.0:
        return 0.0
    if x >= 60.0:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


class BgeRerankerProvider(RerankProvider):
    """Local BGE reranker v2-m3 cross-encoder, loaded lazily off the event loop."""

    name = "bge-reranker"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.model = settings.rerank_model
        self._model = None
        self._lock = asyncio.Lock()

    def _resolve_device(self) -> str:
        device = self._settings.resolved_embedding_device
        if device == "auto":
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
        return device

    def _load(self):
        if self._settings.hf_home:
            # Must be set before huggingface_hub is first imported: it freezes
            # HF_HOME at import time. Lets .env drive the cache location.
            import os

            os.environ["HF_HOME"] = self._settings.hf_home
        try:
            from FlagEmbedding import FlagReranker
        except ImportError as exc:
            raise RerankError(
                "FlagEmbedding is not installed. Run: pip install -e .[embeddings]"
            ) from exc
        device = self._resolve_device()
        try:
            model = FlagReranker(
                self._settings.rerank_model,
                use_fp16=(device == "cuda"),
                devices=device,
            )
        except Exception as exc:
            raise RerankError(
                f"Could not load reranker model '{self._settings.rerank_model}' "
                f"on {device}. If weights are missing, download them with "
                f"`huggingface-cli download {self._settings.rerank_model}`. "
                f"Details: {exc}"
            ) from exc
        log.info("rerank_model_loaded", model=self.model, device=device)
        return model

    async def _get_model(self):
        if self._model is None:
            async with self._lock:
                if self._model is None:
                    self._model = await asyncio.to_thread(self._load)
        return self._model

    def _score(self, query: str, documents: list[str]) -> list[float]:
        pairs = [(query, doc) for doc in documents]
        raw = self._model.compute_score(
            pairs,
            batch_size=self._settings.embedding_batch_size,
            max_length=512,
        )
        if isinstance(raw, float):
            raw = [raw]
        return [_sigmoid(float(s)) for s in raw]

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        await self._get_model()
        return await asyncio.to_thread(self._score, query, documents)

    async def aclose(self) -> None:
        self._model = None