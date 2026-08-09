"""reviewed tailoring: resume_reviews + resume_patches, and LaTeX-only resumes

Collapses three overlapping tailoring paths into one. A review holds the ATS
verdict for one master against one job; a patch holds one proposed slot change
and the author's decision on it. No child resume exists until every patch is
resolved, which is a rule the server can only enforce if the patches are rows.

`resumes.content_format` goes with them. `.tex` is now the only accepted input,
so the column can only ever hold `'latex'` — and a column that records a fact
already guaranteed by the write path is a place for the two to disagree, which
is exactly how a Markdown document came to be stored as compilable LaTeX.

Any row that is not already `'latex'` is deleted rather than migrated. There is
no honest conversion: a Markdown resume is not a LaTeX document, and inventing a
preamble for one would produce something the author never wrote. The downgrade
recreates the column as `'latex'` for every surviving row, which is lossless in
the only direction that matters — nothing else was left.

Revision ID: e2a7c4b81f60
Revises: b4f21c0a97de
Create Date: 2026-08-09 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e2a7c4b81f60'
down_revision: Union[str, Sequence[str], None] = 'b4f21c0a97de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'resume_reviews',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('master_resume_id', sa.Uuid(), nullable=False),
        sa.Column('job_profile_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='open'),
        sa.Column('match_score', sa.Integer(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('matched_keywords', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('missing_keywords', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('base_hashes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('child_resume_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['master_resume_id'], ['resumes.id'], ondelete='CASCADE'),
        # RESTRICT: a job profile is shared, moderated data. Rejecting one must
        # not silently destroy somebody's in-progress review of it.
        sa.ForeignKeyConstraint(['job_profile_id'], ['job_profiles.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['child_resume_id'], ['resumes.id'], ondelete='SET NULL'),
        sa.CheckConstraint("status IN ('open', 'finalized')", name='ck_resume_reviews_status'),
        sa.CheckConstraint(
            'match_score >= 0 AND match_score <= 100', name='ck_resume_reviews_match_score'
        ),
    )
    op.create_index('ix_resume_reviews_user_id', 'resume_reviews', ['user_id'])
    op.create_index('ix_resume_reviews_master_resume_id', 'resume_reviews', ['master_resume_id'])
    op.create_index('ix_resume_reviews_job_profile_id', 'resume_reviews', ['job_profile_id'])
    op.create_index(
        'ix_resume_reviews_master_created', 'resume_reviews', ['master_resume_id', 'created_at']
    )

    op.create_table(
        'resume_patches',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('review_id', sa.Uuid(), nullable=False),
        sa.Column('slot_id', sa.String(length=32), nullable=False),
        sa.Column('slot_kind', sa.String(length=8), nullable=False),
        sa.Column('section_heading', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('original_items', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('original_latex', sa.Text(), nullable=True),
        sa.Column('proposed_items', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('proposed_latex', sa.Text(), nullable=True),
        sa.Column('initial_items', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('initial_latex', sa.Text(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('severity', sa.String(length=16), nullable=False, server_default='important'),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('feedback', sa.Text(), nullable=True),
        sa.Column('revision_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['review_id'], ['resume_reviews.id'], ondelete='CASCADE'),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')", name='ck_resume_patches_status'
        ),
        sa.CheckConstraint(
            "slot_kind IN ('group', 'region')", name='ck_resume_patches_slot_kind'
        ),
        sa.CheckConstraint(
            "(slot_kind = 'group' AND proposed_items IS NOT NULL AND proposed_latex IS NULL)"
            " OR (slot_kind = 'region' AND proposed_latex IS NOT NULL AND proposed_items IS NULL)",
            name='ck_resume_patches_payload_matches_kind',
        ),
    )
    op.create_index('ix_resume_patches_review_id', 'resume_patches', ['review_id'])
    op.create_index(
        'uq_resume_patches_review_slot', 'resume_patches', ['review_id', 'slot_id'], unique=True
    )

    # Children first: a Markdown master's LaTeX child cannot exist, but the FK
    # would block the parent's delete if one somehow did.
    op.execute(
        "DELETE FROM resumes WHERE master_resume_id IN "
        "(SELECT id FROM resumes WHERE content_format <> 'latex')"
    )
    op.execute("DELETE FROM resumes WHERE content_format <> 'latex'")
    op.drop_constraint('ck_resumes_content_format', 'resumes', type_='check')
    op.drop_column('resumes', 'content_format')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        'resumes',
        sa.Column('content_format', sa.String(length=10), nullable=False, server_default='latex'),
    )
    op.create_check_constraint(
        'ck_resumes_content_format', 'resumes', "content_format IN ('markdown', 'json', 'latex')"
    )
    op.drop_index('uq_resume_patches_review_slot', table_name='resume_patches')
    op.drop_index('ix_resume_patches_review_id', table_name='resume_patches')
    op.drop_table('resume_patches')
    op.drop_index('ix_resume_reviews_master_created', table_name='resume_reviews')
    op.drop_index('ix_resume_reviews_job_profile_id', table_name='resume_reviews')
    op.drop_index('ix_resume_reviews_master_resume_id', table_name='resume_reviews')
    op.drop_index('ix_resume_reviews_user_id', table_name='resume_reviews')
    op.drop_table('resume_reviews')
