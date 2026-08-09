"""per-resume LaTeX slot configuration

Adds `resumes.latex_slot_config`: the vocabulary the parser needs to find the
editable content in a template it does not recognise — see
`app/services/latex/config.py`.

Nullable with no default, and NULL is the meaningful common case rather than a
placeholder: a resume built on `\\item` or `\\resumeItem{...}` is read by the
built-in shapes and stores nothing. Only a template that needed discovering
carries a value, so existing rows are correct as they stand and there is no
backfill.

JSONB rather than JSON because the column is read on every parse and will be
queried by `source`/`confirmed` once the review UI exists.

Revision ID: b4f21c0a97de
Revises: c861d7e2f9e3
Create Date: 2026-08-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b4f21c0a97de'
down_revision: Union[str, Sequence[str], None] = 'c861d7e2f9e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'resumes',
        sa.Column('latex_slot_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('resumes', 'latex_slot_config')
