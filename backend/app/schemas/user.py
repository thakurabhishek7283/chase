import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr


class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
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
    current_title: str | None
    career_goals: str | None
    desired_salary_min: Decimal | None
    desired_salary_max: Decimal | None
    salary_currency: str
    created_at: datetime
    updated_at: datetime
