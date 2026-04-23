import pytest

from app.core.config import Settings
from app.embeddings import EmbeddingError, build_provider
from app.embeddings.base import EmbeddingProvider


class StubProvider(EmbeddingProvider):
    """Deterministic provider used to exercise the interface contract."""

    @property
    def dimension(self) -> int:
        return 3

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0, 0.0] for text in texts]


async def test_embed_one_delegates_to_embed() -> None:
    provider = StubProvider()
    assert await provider.embed_one("abcd") == [4.0, 1.0, 0.0]


async def test_embed_preserves_input_order() -> None:
    provider = StubProvider()
    vectors = await provider.embed(["a", "bbb", "cc"])
    assert [vector[0] for vector in vectors] == [1.0, 3.0, 2.0]


async def test_embed_handles_empty_batch() -> None:
    assert await StubProvider().embed([]) == []


def test_build_provider_selects_local_by_default() -> None:
    provider = build_provider(Settings(embedding_provider="local", embedding_dim=384))
    assert provider.dimension == 384


def test_build_provider_requires_voyage_key() -> None:
    with pytest.raises(EmbeddingError, match="VOYAGE_API_KEY"):
        build_provider(Settings(embedding_provider="voyage", voyage_api_key=None))


def test_build_provider_requires_openai_key() -> None:
    with pytest.raises(EmbeddingError, match="OPENAI_API_KEY"):
        build_provider(Settings(embedding_provider="openai", openai_api_key=None))


def test_build_provider_honours_configured_dimension() -> None:
    provider = build_provider(
        Settings(embedding_provider="voyage", voyage_api_key="k", embedding_dim=1024)
    )
    assert provider.dimension == 1024
