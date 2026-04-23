import asyncio
from functools import lru_cache

from app.embeddings.base import EmbeddingError, EmbeddingProvider


@lru_cache(maxsize=4)
def _load_model(model_name: str):
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise EmbeddingError(
            "The local embedding provider requires fastembed. "
            "Install it with: uv sync --extra local-embeddings"
        ) from exc
    return TextEmbedding(model_name=model_name)


class LocalEmbeddingProvider(EmbeddingProvider):
    """Runs an ONNX embedding model on this machine — no API key, no per-call cost.

    The model is downloaded once on first use and cached on disk by fastembed.
    """

    def __init__(self, model_name: str, dimension: int) -> None:
        self._model_name = model_name
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # fastembed is synchronous and CPU-bound; keep it off the event loop.
        return await asyncio.to_thread(self._embed_sync, texts)

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        model = _load_model(self._model_name)
        vectors = [vector.tolist() for vector in model.embed(texts)]
        for vector in vectors:
            if len(vector) != self._dimension:
                raise EmbeddingError(
                    f"Model {self._model_name} returned {len(vector)}-dim vectors "
                    f"but settings declare embedding_dim={self._dimension}."
                )
        return vectors
