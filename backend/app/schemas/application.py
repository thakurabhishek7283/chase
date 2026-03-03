import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.company import CompanyRead
from app.schemas.job_profile import JobProfileRead
from app.schemas.resume import ResumeRead

Stage = Literal["applied", "interviewing", "offer", "archive"]


class ApplicationCreate(BaseModel):
    user_id: uuid.UUID
    company_id: uuid.UUID
    job_profile_id: uuid.UUID
    resume_id: uuid.UUID
    stage: Stage = "applied"
    board_position: int = 0
    applied_date: date | None = None
    notes: str | None = None


class ApplicationUpdate(BaseModel):
    resume_id: uuid.UUID | None = None
    board_position: int | None = None
    applied_date: date | None = None
    notes: str | None = None


class ApplicationStageUpdate(BaseModel):
    stage: Stage
    board_position: int


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    company_id: uuid.UUID
    job_profile_id: uuid.UUID
    resume_id: uuid.UUID
    stage: str
    board_position: int
    stage_updated_at: datetime
    applied_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ApplicationReadWithDetails(ApplicationRead):
    company: CompanyRead
    job_profile: JobProfileRead
    resume: ResumeRead
