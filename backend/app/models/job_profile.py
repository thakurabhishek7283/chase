import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, Index, text
from sqlmodel import Field, SQLModel

from app.models.moderation import status_check, status_constraint_name


def _utcnow() -> datetime:
    return datetime.now(UTC)


class JobProfile(SQLModel, table=True):
    __tablename__ = "job_profiles"
    __table_args__ = (
        CheckConstraint(
            "experience_tier IN ('intern', 'junior', 'mid', 'senior', 'staff', 'principal', 'executive')",
            name="ck_job_profiles_experience_tier",
        ),
        CheckConstraint(status_check("job_profiles"), name=status_constraint_name("job_profiles")),
        # The identity of a posting is (company, requisition id) — the key the
        # employer themselves uses. Partial for two reasons: Postgres treats
        # NULLs as distinct, so a plain UNIQUE over a nullable column would
        # admit unlimited rows with no job id; and rejected rows are excluded
        # so a junk submission cannot squat a real requisition id forever.
        Index(
            "uq_job_profiles_company_external_id",
            "company_id",
            "external_job_id",
            unique=True,
            postgresql_where=text("external_job_id IS NOT NULL AND status <> 'rejected'"),
        ),
        # Plenty of postings expose no requisition id. For those, title +
        # location within a company is the best available identity. Case- and
        # NULL-normalised so "Senior Engineer"/"senior engineer" and a missing
        # location collide the way a human would expect them to.
        Index(
            "uq_job_profiles_company_title_location",
            "company_id",
            text("lower(position_title)"),
            text("lower(coalesce(location, ''))"),
            unique=True,
            postgresql_where=text("external_job_id IS NULL AND status <> 'rejected'"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    #: The employer's own requisition id, scraped from the posting URL or the
    #: listing itself. Nullable because not every posting shows one.
    external_job_id: str | None = Field(default=None, max_length=128)
    position_title: str = Field(max_length=255)
    experience_tier: str | None = Field(default=None, max_length=20)
    description: str
    location: str | None = Field(default=None, max_length=255)
    employment_type: str | None = Field(default=None, max_length=50)

    # --- moderation ----------------------------------------------------------
    status: str = Field(default="pending", max_length=20, index=True)
    created_by: uuid.UUID | None = Field(default=None, foreign_key="users.id", index=True)
    reviewed_by: uuid.UUID | None = Field(default=None, foreign_key="users.id")
    reviewed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    rejection_reason: str | None = Field(default=None)

    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
