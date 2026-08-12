from abc import ABC, abstractmethod


class EmbeddingError(RuntimeError):
    """Raised when an embedding provider is unavailable or fails."""


class EmbeddingProvider(ABC):
    """Provider-agnostic embedding interface.

    Gemini is the reasoning model but not the embedding one: Phase 2 semantic
    matching runs on-machine (see `local.py`). The interface stays abstract so
    a hosted provider can be added without touching the matching service.
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
