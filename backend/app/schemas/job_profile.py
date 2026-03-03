import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.technology import TechnologyRead

ExperienceTier = Literal[
    "intern", "junior", "mid", "senior", "staff", "principal", "executive"
]


class JobProfileCreate(BaseModel):
    company_id: uuid.UUID
    position_title: str
    experience_tier: ExperienceTier | None = None
    description: str
    location: str | None = None
    employment_type: str | None = None


class JobProfileUpdate(BaseModel):
    position_title: str | None = None
    experience_tier: ExperienceTier | None = None
    description: str | None = None
    location: str | None = None
    employment_type: str | None = None


class JobProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    position_title: str
    experience_tier: str | None
    description: str
    location: str | None
    employment_type: str | None
    created_at: datetime
    updated_at: datetime


class JobProfileReadWithTechnologies(JobProfileRead):
    technologies: list[TechnologyRead] = []
