import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Company(SQLModel, table=True):
    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint(
            "growth_trajectory IN ('declining', 'stable', 'growing', 'hypergrowth')",
            name="ck_companies_growth_trajectory",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=255, unique=True, index=True)
    industry: str | None = Field(default=None, max_length=255)
    growth_trajectory: str | None = Field(default=None, max_length=20)
    website: str | None = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
