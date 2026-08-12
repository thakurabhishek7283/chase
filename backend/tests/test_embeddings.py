from app.core.config import Settings
from app.embeddings import LocalEmbeddingProvider, build_provider
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


def test_build_provider_returns_the_local_provider() -> None:
    provider = build_provider(Settings(embedding_dim=384))
    assert isinstance(provider, LocalEmbeddingProvider)
    assert provider.dimension == 384


def test_build_provider_honours_configured_dimension() -> None:
    # The declared dimension must follow the pgvector column, so it is read
    # from settings rather than hard-coded to the default model's width.
    assert build_provider(Settings(embedding_dim=1024)).dimension == 1024
