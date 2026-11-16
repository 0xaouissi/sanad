from abc import ABC, abstractmethod


class RerankError(Exception):
    """Reranker failure. The message tells the user how to fix it."""


class RerankProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Return relevance probabilities in [0, 1], one per document, in order."""

    async def aclose(self) -> None:
        return None