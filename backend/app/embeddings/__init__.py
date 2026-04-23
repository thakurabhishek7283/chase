from functools import lru_cache

from app.core.config import Settings, get_settings
from app.embeddings.base import EmbeddingError, EmbeddingProvider
from app.embeddings.local import LocalEmbeddingProvider
from app.embeddings.remote import (
    GeminiEmbeddingProvider,
    OpenAIEmbeddingProvider,
    VoyageEmbeddingProvider,
)


def build_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "local":
        return LocalEmbeddingProvider(settings.local_embedding_model, settings.embedding_dim)
    if settings.embedding_provider == "voyage":
        if not settings.voyage_api_key:
            raise EmbeddingError("embedding_provider='voyage' requires VOYAGE_API_KEY.")
        return VoyageEmbeddingProvider(
            settings.voyage_api_key, settings.voyage_model, settings.embedding_dim
        )
    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            raise EmbeddingError("embedding_provider='openai' requires OPENAI_API_KEY.")
        return OpenAIEmbeddingProvider(
            settings.openai_api_key, settings.openai_embedding_model, settings.embedding_dim
        )
    if settings.embedding_provider == "gemini":
        if not settings.google_api_key:
            raise EmbeddingError("embedding_provider='gemini' requires GOOGLE_API_KEY.")
        return GeminiEmbeddingProvider(
            settings.google_api_key, settings.gemini_embedding_model, settings.embedding_dim
        )
    raise EmbeddingError(f"Unknown embedding provider: {settings.embedding_provider}")


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    return build_provider(get_settings())


__all__ = [
    "EmbeddingError",
    "EmbeddingProvider",
    "GeminiEmbeddingProvider",
    "LocalEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "VoyageEmbeddingProvider",
    "build_provider",
    "get_embedding_provider",
]
