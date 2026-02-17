import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobProfile(SQLModel, table=True):
    __tablename__ = "job_profiles"
    __table_args__ = (
        CheckConstraint(
            "experience_tier IN ('intern', 'junior', 'mid', 'senior', 'staff', 'principal', 'executive')",
            name="ck_job_profiles_experience_tier",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    position_title: str = Field(max_length=255)
    experience_tier: str | None = Field(default=None, max_length=20)
    description: str
    location: str | None = Field(default=None, max_length=255)
    employment_type: str | None = Field(default=None, max_length=50)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
