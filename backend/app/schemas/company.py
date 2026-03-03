import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.technology import TechnologyRead

GrowthTrajectory = Literal["declining", "stable", "growing", "hypergrowth"]


class CompanyCreate(BaseModel):
    name: str
    industry: str | None = None
    growth_trajectory: GrowthTrajectory | None = None
    website: str | None = None


class CompanyUpdate(BaseModel):
    name: str | None = None
    industry: str | None = None
    growth_trajectory: GrowthTrajectory | None = None
    website: str | None = None


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    industry: str | None
    growth_trajectory: str | None
    website: str | None
    created_at: datetime
    updated_at: datetime


class CompanyReadWithTechnologies(CompanyRead):
    technologies: list[TechnologyRead] = []
