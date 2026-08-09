import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.auth import Password


class UserCreate(BaseModel):
    """Admin-side provisioning. Ordinary signup goes through `/auth/register`."""

    full_name: str
    email: EmailStr
    password: Password
    role: str | None = Field(default=None, pattern="^(user|moderator|admin)$")
    current_title: str | None = None
    career_goals: str | None = None
    desired_salary_min: Decimal | None = None
    desired_salary_max: Decimal | None = None
    salary_currency: str = "USD"


class UserUpdate(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    current_title: str | None = None
    career_goals: str | None = None
    desired_salary_min: Decimal | None = None
    desired_salary_max: Decimal | None = None
    salary_currency: str | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str
    role: str
    is_active: bool
    current_title: str | None
    career_goals: str | None
    desired_salary_min: Decimal | None
    desired_salary_max: Decimal | None
    salary_currency: str
    created_at: datetime
    updated_at: datetime
