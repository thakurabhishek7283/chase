"""phase1 initial schema

Revision ID: eb33c6adc51f
Revises: ca59c8073283
Create Date: 2026-07-30 23:08:17.384065

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'eb33c6adc51f'
down_revision: Union[str, Sequence[str], None] = 'ca59c8073283'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("current_title", sa.String(length=255), nullable=True),
        sa.Column("career_goals", sa.Text(), nullable=True),
        sa.Column("desired_salary_min", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("desired_salary_max", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("salary_currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("industry", sa.String(length=255), nullable=True),
        sa.Column("growth_trajectory", sa.String(length=20), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "growth_trajectory IN ('declining', 'stable', 'growing', 'hypergrowth')",
            name="ck_companies_growth_trajectory",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_companies_name"), "companies", ["name"], unique=True)

    op.create_table(
        "technologies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_technologies_name"), "technologies", ["name"], unique=True)

    op.create_table(
        "job_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("position_title", sa.String(length=255), nullable=False),
        sa.Column("experience_tier", sa.String(length=20), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("employment_type", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "experience_tier IN ('intern', 'junior', 'mid', 'senior', 'staff', 'principal', 'executive')",
            name="ck_job_profiles_experience_tier",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_job_profiles_company_id"), "job_profiles", ["company_id"], unique=False)

    op.create_table(
        "resumes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("master_resume_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content_format", sa.String(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version_label", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "content_format IN ('markdown', 'json')", name="ck_resumes_content_format"
        ),
        sa.ForeignKeyConstraint(["master_resume_id"], ["resumes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_resumes_user_id"), "resumes", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_resumes_master_resume_id"), "resumes", ["master_resume_id"], unique=False
    )

    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("job_profile_id", sa.Uuid(), nullable=False),
        sa.Column("resume_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("board_position", sa.Integer(), nullable=False),
        sa.Column("stage_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "stage IN ('applied', 'interviewing', 'offer', 'archive')",
            name="ck_applications_stage",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["job_profile_id"], ["job_profiles.id"]),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_applications_user_id"), "applications", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_applications_company_id"), "applications", ["company_id"], unique=False
    )
    op.create_index(
        op.f("ix_applications_job_profile_id"), "applications", ["job_profile_id"], unique=False
    )
    op.create_index(
        op.f("ix_applications_resume_id"), "applications", ["resume_id"], unique=False
    )
    op.create_index(op.f("ix_applications_stage"), "applications", ["stage"], unique=False)

    op.create_table(
        "company_technologies",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("technology_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["technology_id"], ["technologies.id"]),
        sa.PrimaryKeyConstraint("company_id", "technology_id"),
    )

    op.create_table(
        "job_profile_technologies",
        sa.Column("job_profile_id", sa.Uuid(), nullable=False),
        sa.Column("technology_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_level", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "requirement_level IN ('required', 'nice_to_have')",
            name="ck_job_profile_technologies_requirement_level",
        ),
        sa.ForeignKeyConstraint(["job_profile_id"], ["job_profiles.id"]),
        sa.ForeignKeyConstraint(["technology_id"], ["technologies.id"]),
        sa.PrimaryKeyConstraint("job_profile_id", "technology_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("job_profile_technologies")
    op.drop_table("company_technologies")
    op.drop_index(op.f("ix_applications_stage"), table_name="applications")
    op.drop_index(op.f("ix_applications_resume_id"), table_name="applications")
    op.drop_index(op.f("ix_applications_job_profile_id"), table_name="applications")
    op.drop_index(op.f("ix_applications_company_id"), table_name="applications")
    op.drop_index(op.f("ix_applications_user_id"), table_name="applications")
    op.drop_table("applications")
    op.drop_index(op.f("ix_resumes_master_resume_id"), table_name="resumes")
    op.drop_index(op.f("ix_resumes_user_id"), table_name="resumes")
    op.drop_table("resumes")
    op.drop_index(op.f("ix_job_profiles_company_id"), table_name="job_profiles")
    op.drop_table("job_profiles")
    op.drop_index(op.f("ix_technologies_name"), table_name="technologies")
    op.drop_table("technologies")
    op.drop_index(op.f("ix_companies_name"), table_name="companies")
    op.drop_table("companies")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
