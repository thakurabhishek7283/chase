import math

import httpx

from app.embeddings.base import EmbeddingError, EmbeddingProvider


class VoyageEmbeddingProvider(EmbeddingProvider):
    """Voyage AI — Anthropic's recommended embeddings partner."""

    def __init__(self, api_key: str, model: str, dimension: int) -> None:
        self._api_key = api_key
        self._model = model
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.voyageai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"input": texts, "model": self._model},
            )
        if response.status_code != 200:
            raise EmbeddingError(f"Voyage embeddings failed ({response.status_code}): {response.text}")
        payload = response.json()
        ordered = sorted(payload["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in ordered]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embeddings — note this introduces a second AI vendor to the stack."""

    def __init__(self, api_key: str, model: str, dimension: int) -> None:
        self._api_key = api_key
        self._model = model
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"input": texts, "model": self._model},
            )
        if response.status_code != 200:
            raise EmbeddingError(f"OpenAI embeddings failed ({response.status_code}): {response.text}")
        payload = response.json()
        ordered = sorted(payload["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in ordered]


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Google Gemini embeddings.

    Useful when Gemini is already the reasoning provider — one vendor and one
    credential for the whole AI stack instead of two.

    Two Gemini-specific details are handled here:

    - **Dimension is requested, not fixed.** The model natively emits 3072
      dimensions and truncates via `outputDimensionality` (Matryoshka
      representation learning), so it can be asked for whatever the pgvector
      column was built for.
    - **Truncated vectors need re-normalising.** `gemini-embedding-001` does not
      re-normalise when truncated, which silently breaks cosine distance —
      pgvector's `vector_cosine_ops` assumes unit vectors. Normalising here is
      cheap and makes the provider correct at any dimension; `gemini-embedding-2`
      already normalises, and re-normalising a unit vector is a no-op.
    """

    _ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"

    def __init__(self, api_key: str, model: str, dimension: int) -> None:
        self._api_key = api_key
        self._model = model
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    @staticmethod
    def _unit(vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = self._ENDPOINT.format(model=self._model)
        headers = {"x-goog-api-key": self._api_key}
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            # The REST endpoint embeds one document per call; batching lives
            # behind :batchEmbedContents, which is not worth the extra shape
            # for the handful of documents this app indexes.
            for text in texts:
                response = await client.post(
                    url,
                    headers=headers,
                    json={
                        "model": f"models/{self._model}",
                        "content": {"parts": [{"text": text}]},
                        "outputDimensionality": self._dimension,
                    },
                )
                if response.status_code != 200:
                    raise EmbeddingError(
                        f"Gemini embeddings failed ({response.status_code}): {response.text}"
                    )
                vectors.append(self._unit(response.json()["embedding"]["values"]))
        return vectors
