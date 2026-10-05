import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.config import get_settings


def _utcnow() -> datetime:
    return datetime.now(UTC)


#: Entity kinds that can carry an embedding. Kept as a CHECK-constrained string
#: rather than a native enum — widening a CHECK later stays a one-line
#: migration, while `ALTER TYPE … ADD VALUE` is not.
EMBEDDABLE_ENTITIES = ("user_career_goals", "job_profile", "company", "resume")


class EntityEmbedding(SQLModel, table=True):
    """Vector embeddings for semantic matching, kept out of the core tables.

    This is the only table that depends on the `pgvector` extension. Isolating
    it means the Phase 1 relational schema stays usable on a Postgres instance
    where pgvector isn't installed — the semantic-matching endpoints degrade
    with a clear error instead of the whole app failing to start.
    """

    __tablename__ = "entity_embeddings"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('user_career_goals', 'job_profile', 'company', 'resume')",
            name="ck_entity_embeddings_entity_type",
        ),
        UniqueConstraint("entity_type", "entity_id", name="uq_entity_embeddings_entity"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    entity_type: str = Field(max_length=32, index=True)
    entity_id: uuid.UUID = Field(index=True)
    #: Source text the vector was derived from — lets us detect staleness
    #: without re-embedding, and makes stored vectors auditable.
    source_text: str
    provider: str = Field(max_length=32)
    model: str = Field(max_length=128)
    embedding: list[float] = Field(
        sa_column=Column(Vector(get_settings().embedding_dim), nullable=False)
    )
    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
