from abc import ABC, abstractmethod


class EmbeddingError(RuntimeError):
    pass


class EmbeddingProvider(ABC):
    name: str
    model: str
    dim: int

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into dense vectors."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release model resources."""