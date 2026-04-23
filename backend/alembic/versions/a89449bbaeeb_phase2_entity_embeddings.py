"""phase2 entity embeddings

Revision ID: a89449bbaeeb
Revises: eb33c6adc51f
Create Date: 2026-07-30 23:56:32.063880

Requires the `pgvector` extension (migration ca59c8073283). Where pgvector is
absent this migration is skipped rather than failing: the revisions stacked on
top of it carry unrelated Phase 5 schema, and failing here would block all of
them on any Postgres that did not come from the pgvector Docker image.

The trade-off is that `entity_embeddings` can be missing while Alembic reports
head. That is the state the matching service already expects -- it catches the
missing table and raises `VectorSearchUnavailableError`, surfaced as a 503.

The vector dimension is read from settings so it tracks the configured
embedding provider. Switching to a provider with a different dimension needs a
follow-up migration; it is not a runtime-tunable value.
"""
import logging
from typing import Sequence, Union

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op
from app.core.config import get_settings

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = 'a89449bbaeeb'
down_revision: Union[str, Sequence[str], None] = 'eb33c6adc51f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    installed = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    ).scalar()
    if not installed:
        logger.warning(
            "pgvector extension absent - skipping the entity_embeddings table. "
            "Semantic matching returns 503 until pgvector is installed and this "
            "table is created."
        )
        return

    dim = get_settings().embedding_dim

    op.create_table(
        "entity_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("embedding", Vector(dim), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('user_career_goals', 'job_profile', 'company', 'resume')",
            name="ck_entity_embeddings_entity_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_type", "entity_id", name="uq_entity_embeddings_entity"),
    )
    op.create_index(
        op.f("ix_entity_embeddings_entity_type"), "entity_embeddings", ["entity_type"], unique=False
    )
    op.create_index(
        op.f("ix_entity_embeddings_entity_id"), "entity_embeddings", ["entity_id"], unique=False
    )
    # HNSW beats IVFFlat for the small, frequently-updated corpus this app has:
    # it needs no training step and stays accurate as rows trickle in.
    op.execute(
        "CREATE INDEX ix_entity_embeddings_vector "
        "ON entity_embeddings USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # IF EXISTS throughout: the upgrade is a no-op without pgvector, so a
    # downgrade may find nothing to drop.
    op.execute("DROP INDEX IF EXISTS ix_entity_embeddings_vector")
    op.execute("DROP INDEX IF EXISTS ix_entity_embeddings_entity_id")
    op.execute("DROP INDEX IF EXISTS ix_entity_embeddings_entity_type")
    op.execute("DROP TABLE IF EXISTS entity_embeddings")
