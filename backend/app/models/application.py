import uuid
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.job_profile import JobProfile
    from app.models.resume import Resume


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Application(SQLModel, table=True):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('applied', 'interviewing', 'offer', 'archive')",
            name="ck_applications_stage",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    job_profile_id: uuid.UUID = Field(foreign_key="job_profiles.id", index=True)
    resume_id: uuid.UUID = Field(foreign_key="resumes.id", index=True)
    stage: str = Field(default="applied", max_length=20, index=True)
    board_position: int = Field(default=0)
    stage_updated_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
    applied_date: date | None = Field(default=None)
    notes: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))

    company: "Company" = Relationship()
    job_profile: "JobProfile" = Relationship()
    resume: "Resume" = Relationship()
