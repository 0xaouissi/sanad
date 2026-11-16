import asyncio

import structlog

from app.core.config import Settings
from app.providers.embeddings.base import EmbeddingError, EmbeddingProvider

log = structlog.get_logger()


class BgeM3Provider(EmbeddingProvider):
    """Local BGE-M3 dense embeddings (1024-dim), loaded lazily off the event loop."""

    name = "bge-m3"
    dim = 1024

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.model = settings.embedding_model
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
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:
            raise EmbeddingError(
                "FlagEmbedding is not installed. Run: pip install -e .[embeddings]"
            ) from exc
        device = self._resolve_device()
        try:
            model = BGEM3FlagModel(
                self._settings.embedding_model,
                use_fp16=(device == "cuda"),
                device=device,
            )
        except Exception as exc:
            raise EmbeddingError(
                f"Could not load embedding model '{self._settings.embedding_model}' "
                f"on {device}. If weights are missing, download them with "
                "`huggingface-cli download BAAI/bge-m3` (see README). "
                f"Details: {exc}"
            ) from exc
        log.info("embedding_model_loaded", model=self.model, device=device)
        return model

    async def _get_model(self):
        if self._model is None:
            async with self._lock:
                if self._model is None:
                    self._model = await asyncio.to_thread(self._load)
        return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        output = self._model.encode(
            texts,
            batch_size=self._settings.embedding_batch_size,
            max_length=1024,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        return [vec.tolist() for vec in output["dense_vecs"]]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        await self._get_model()
        return await asyncio.to_thread(self._encode, texts)

    async def aclose(self) -> None:
        self._model = None