"""phase5 latex content format

Revision ID: c7d2f1a4b830
Revises: a89449bbaeeb
Create Date: 2026-07-31 01:20:00.000000

Admits 'latex' to the resumes.content_format check constraint.

A LaTeX master needs no table of its own: the template *is* the master's `.tex`
source, already stored in resumes.content, and the existing master_resume_id
self-reference already links a tailored child to the master it was rendered
from. The span map that drives tailoring is derived deterministically from the
source on every request, so persisting it would only create a cache that can
fall out of step with the document it describes.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c7d2f1a4b830'
down_revision: Union[str, Sequence[str], None] = 'a89449bbaeeb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = "content_format IN ('markdown', 'json')"
_NEW = "content_format IN ('markdown', 'json', 'latex')"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("ck_resumes_content_format", "resumes", type_="check")
    op.create_check_constraint("ck_resumes_content_format", "resumes", _NEW)


def downgrade() -> None:
    """Downgrade schema."""
    # Rows added under the widened constraint would violate the narrow one, so
    # they are converted rather than left to fail the constraint creation.
    op.execute("UPDATE resumes SET content_format = 'markdown' WHERE content_format = 'latex'")
    op.drop_constraint("ck_resumes_content_format", "resumes", type_="check")
    op.create_check_constraint("ck_resumes_content_format", "resumes", _OLD)
