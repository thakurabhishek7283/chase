import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict


class TechnologyCreate(BaseModel):
    name: str
    category: str | None = None


class TechnologyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str | None


class CompanyTechnologyAttach(BaseModel):
    technology_name: str
    category: str | None = None


class JobProfileTechnologyAttach(BaseModel):
    technology_name: str
    category: str | None = None
    requirement_level: Literal["required", "nice_to_have"] = "required"
