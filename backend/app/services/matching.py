import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings
from app.embeddings import PROVIDER_NAME, EmbeddingProvider
from app.models.embedding import EntityEmbedding
from app.models.job_profile import JobProfile


class VectorSearchUnavailableError(RuntimeError):
    """Raised when the pgvector-backed tables are missing.

    Phase 2's vector migration is intentionally deferred until pgvector is
    installed, so this is an expected operational state, not a bug.
    """


_MISSING_TABLE_MESSAGE = (
    "Semantic search needs the pgvector extension and the "
    "'phase2 entity embeddings' migration. Run `alembic upgrade head` "
    "against a Postgres instance with pgvector installed."
)


def build_job_profile_text(job: JobProfile) -> str:
    """Flatten a job profile into the text that gets embedded."""
    parts = [job.position_title, job.experience_tier or "", job.location or "", job.description]
    return "\n".join(part for part in parts if part)


async def upsert_embedding(
    session: AsyncSession,
    provider: EmbeddingProvider,
    settings: Settings,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    source_text: str,
) -> EntityEmbedding:
    """Embed `source_text` and store it, replacing any existing vector.

    Skips re-embedding when the stored vector already came from identical text
    on the same provider/model — embedding calls are the expensive step here.
    """
    try:
        result = await session.exec(
            select(EntityEmbedding).where(
                EntityEmbedding.entity_type == entity_type,
                EntityEmbedding.entity_id == entity_id,
            )
        )
        existing = result.first()
    except ProgrammingError as exc:
        await session.rollback()
        raise VectorSearchUnavailableError(_MISSING_TABLE_MESSAGE) from exc

    model_name = settings.local_embedding_model
    if (
        existing is not None
        and existing.source_text == source_text
        and existing.provider == PROVIDER_NAME
        and existing.model == model_name
    ):
        return existing

    vector = await provider.embed_one(source_text)
    now = datetime.now(UTC)

    if existing is None:
        existing = EntityEmbedding(
            entity_type=entity_type,
            entity_id=entity_id,
            source_text=source_text,
            provider=PROVIDER_NAME,
            model=model_name,
            embedding=vector,
        )
    else:
        existing.source_text = source_text
        existing.provider = PROVIDER_NAME
        existing.model = model_name
        existing.embedding = vector
        existing.updated_at = now

    session.add(existing)
    await session.commit()
    await session.refresh(existing)
    return existing


async def find_similar(
    session: AsyncSession,
    query_vector: list[float],
    *,
    entity_type: str,
    limit: int = 10,
) -> list[tuple[uuid.UUID, float]]:
    """Return (entity_id, similarity) ordered most-similar-first.

    Uses pgvector's cosine distance operator (`<=>`); similarity is reported as
    `1 - distance` so callers get an intuitive 0..1 score.
    """
    statement = text(
        """
        SELECT entity_id, 1 - (embedding <=> CAST(:query AS vector)) AS similarity
        FROM entity_embeddings
        WHERE entity_type = :entity_type
        ORDER BY embedding <=> CAST(:query AS vector)
        LIMIT :limit
        """
    )
    try:
        result = await session.exec(
            statement,
            params={
                "query": _to_pgvector_literal(query_vector),
                "entity_type": entity_type,
                "limit": limit,
            },
        )
    except ProgrammingError as exc:
        await session.rollback()
        raise VectorSearchUnavailableError(_MISSING_TABLE_MESSAGE) from exc
    return [(row[0], float(row[1])) for row in result.all()]


def _to_pgvector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"
