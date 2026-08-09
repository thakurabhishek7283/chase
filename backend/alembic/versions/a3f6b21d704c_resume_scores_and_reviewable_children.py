"""cached ATS scores, and reviews that name a source rather than a master

Two changes, one theme: a tailored resume is now a document you can score and
improve, not a dead end.

`resume_scores` caches one ATS verdict per (resume, job). Scoring costs a model
call; looking at a score should not, and the resume screen wants to open showing
what every version already scores. `content_hash` records the document that was
actually scored so a stale number can be labelled rather than quietly served.

`resume_reviews.master_resume_id` becomes `source_resume_id`. The column always
held "the resume this review was made against"; it only happened to be a master
because reviewing a child was refused. Now that it is not, the old name would be
wrong on exactly the rows the feature exists for. The renamed column keeps its
data, its FK and its indexes — no review is rewritten by this.

Revision ID: a3f6b21d704c
Revises: e2a7c4b81f60
Create Date: 2026-08-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a3f6b21d704c'
down_revision: Union[str, Sequence[str], None] = 'e2a7c4b81f60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'resume_scores',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('resume_id', sa.Uuid(), nullable=False),
        sa.Column('job_profile_id', sa.Uuid(), nullable=False),
        sa.Column('content_hash', sa.String(length=32), nullable=False),
        sa.Column('match_score', sa.Integer(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('matched_keywords', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('missing_keywords', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['resume_id'], ['resumes.id'], ondelete='CASCADE'),
        # CASCADE, unlike the RESTRICT a review puts on a job profile. A review
        # is a record of somebody's work; a score is a cached derivation, and
        # when either side of it goes the number describes nothing.
        sa.ForeignKeyConstraint(['job_profile_id'], ['job_profiles.id'], ondelete='CASCADE'),
        sa.CheckConstraint(
            'match_score >= 0 AND match_score <= 100', name='ck_resume_scores_match_score'
        ),
    )
    op.create_index('ix_resume_scores_user_id', 'resume_scores', ['user_id'])
    op.create_index('ix_resume_scores_resume_id', 'resume_scores', ['resume_id'])
    op.create_index('ix_resume_scores_job_profile_id', 'resume_scores', ['job_profile_id'])
    op.create_index(
        'uq_resume_scores_resume_job', 'resume_scores', ['resume_id', 'job_profile_id'], unique=True
    )

    op.alter_column('resume_reviews', 'master_resume_id', new_column_name='source_resume_id')
    # Postgres carries an index's definition through a column rename but not its
    # name, so both indexes would keep saying `master` forever.
    op.execute(
        'ALTER INDEX ix_resume_reviews_master_resume_id '
        'RENAME TO ix_resume_reviews_source_resume_id'
    )
    op.execute(
        'ALTER INDEX ix_resume_reviews_master_created '
        'RENAME TO ix_resume_reviews_source_created'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        'ALTER INDEX ix_resume_reviews_source_created '
        'RENAME TO ix_resume_reviews_master_created'
    )
    op.execute(
        'ALTER INDEX ix_resume_reviews_source_resume_id '
        'RENAME TO ix_resume_reviews_master_resume_id'
    )
    op.alter_column('resume_reviews', 'source_resume_id', new_column_name='master_resume_id')

    op.drop_index('uq_resume_scores_resume_job', table_name='resume_scores')
    op.drop_index('ix_resume_scores_job_profile_id', table_name='resume_scores')
    op.drop_index('ix_resume_scores_resume_id', table_name='resume_scores')
    op.drop_index('ix_resume_scores_user_id', table_name='resume_scores')
    op.drop_table('resume_scores')
