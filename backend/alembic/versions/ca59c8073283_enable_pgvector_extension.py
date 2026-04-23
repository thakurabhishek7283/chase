"""enable pgvector extension

Revision ID: ca59c8073283
Revises:
Create Date: 2026-07-30 23:07:20.974042

pgvector arrived with the `pgvector/pgvector:pg16` Docker image this project
used to require. Against a stock Postgres the extension's files are absent, and
`CREATE EXTENSION IF NOT EXISTS` still fails in that case ("could not open
extension control file") -- the IF NOT EXISTS covers an already-created
extension, not a missing one. That would strand the migration chain on its
first revision and take the entire relational schema with it.

So availability is checked first and the statement skipped when pgvector is not
present. Vector search is the only feature that degrades.
"""
import logging
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = 'ca59c8073283'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    available = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
    ).scalar()
    if not available:
        logger.warning(
            "pgvector is not installed on this Postgres server - skipping "
            "CREATE EXTENSION. Semantic matching will return 503; the rest of "
            "the schema applies normally."
        )
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP EXTENSION IF EXISTS vector")
