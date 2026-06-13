"""phase5 per-resume latex engine

Revision ID: d1e8b6c93f27
Revises: c7d2f1a4b830
Create Date: 2026-08-01 10:05:00.000000

Adds `resumes.latex_engine` so a master that needs XeLaTeX (fontspec) and one
that needs pdfLaTeX can coexist. NULL means "use LATEX_ENGINE_PATH".

The CHECK constraint is not decoration. The column's value is passed to
`shutil.which()` and then executed as a subprocess, so the database is the last
line of defence behind the Pydantic Literal and the allowlist in
`services/latex/engines.py`. Widening the set of engines means widening all
three.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd1e8b6c93f27'
down_revision: Union[str, Sequence[str], None] = 'c7d2f1a4b830'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENGINES = "('tectonic', 'latexmk', 'pdflatex', 'xelatex', 'lualatex')"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("resumes", sa.Column("latex_engine", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        "ck_resumes_latex_engine",
        "resumes",
        f"latex_engine IS NULL OR latex_engine IN {_ENGINES}",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_resumes_latex_engine", "resumes", type_="check")
    op.drop_column("resumes", "latex_engine")
