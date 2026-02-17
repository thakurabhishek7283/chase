import uuid

from sqlalchemy import CheckConstraint
from sqlmodel import Field, SQLModel


class Technology(SQLModel, table=True):
    __tablename__ = "technologies"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=100, unique=True, index=True)
    category: str | None = Field(default=None, max_length=50)


class CompanyTechnology(SQLModel, table=True):
    __tablename__ = "company_technologies"

    company_id: uuid.UUID = Field(foreign_key="companies.id", primary_key=True)
    technology_id: uuid.UUID = Field(foreign_key="technologies.id", primary_key=True)


class JobProfileTechnology(SQLModel, table=True):
    __tablename__ = "job_profile_technologies"
    __table_args__ = (
        CheckConstraint(
            "requirement_level IN ('required', 'nice_to_have')",
            name="ck_job_profile_technologies_requirement_level",
        ),
    )

    job_profile_id: uuid.UUID = Field(foreign_key="job_profiles.id", primary_key=True)
    technology_id: uuid.UUID = Field(foreign_key="technologies.id", primary_key=True)
    requirement_level: str = Field(default="required", max_length=20)
