from functools import lru_cache

from app.core.config import Settings, get_settings
from app.embeddings.base import EmbeddingError, EmbeddingProvider
from app.embeddings.local import LocalEmbeddingProvider

#: Recorded on every `entity_embeddings` row, so vectors stay attributable if a
#: different provider is ever introduced alongside this one.
PROVIDER_NAME = "local"


def build_provider(settings: Settings) -> EmbeddingProvider:
    return LocalEmbeddingProvider(settings.local_embedding_model, settings.embedding_dim)


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    return build_provider(get_settings())


__all__ = [
    "PROVIDER_NAME",
    "EmbeddingError",
    "EmbeddingProvider",
    "LocalEmbeddingProvider",
    "build_provider",
    "get_embedding_provider",
]
