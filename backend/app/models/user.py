import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    full_name: str = Field(max_length=255)
    email: str = Field(max_length=255, unique=True, index=True)
    current_title: str | None = Field(default=None, max_length=255)
    career_goals: str | None = Field(default=None)
    desired_salary_min: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    desired_salary_max: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    salary_currency: str = Field(default="USD", max_length=3)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
