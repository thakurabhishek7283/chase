from abc import ABC, abstractmethod


class EmbeddingError(RuntimeError):
    """Raised when an embedding provider is unavailable or fails."""


class EmbeddingProvider(ABC):
    """Provider-agnostic embedding interface.

    Anthropic does not offer an embeddings endpoint, so Phase 2 semantic
    matching runs through one of several third-party or local providers.
    Implementations must return unit-comparable float vectors of `dimension`
    length so pgvector's cosine distance operator behaves consistently.
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Length of the vectors this provider emits."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts, preserving input order."""

    async def embed_one(self, text: str) -> list[float]:
        vectors = await self.embed([text])
        return vectors[0]
