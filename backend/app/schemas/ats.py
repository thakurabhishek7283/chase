import uuid

from pydantic import BaseModel, Field

from app.ai.schemas import ATSReport, AutofixResult


class ATSScoreRequest(BaseModel):
    """Score a stored resume against a stored job profile."""

    resume_id: uuid.UUID
    job_profile_id: uuid.UUID


class ATSScoreResponse(BaseModel):
    resume_id: uuid.UUID
    job_profile_id: uuid.UUID
    report: ATSReport


class AutofixRequest(BaseModel):
    resume_id: uuid.UUID
    job_profile_id: uuid.UUID
    target_score: int = Field(default=85, ge=0, le=100)
    max_iterations: int | None = Field(default=None, ge=1, le=10)
    #: When true, the improved resume is saved as a tailored child of the
    #: original rather than only being returned to the caller.
    save_as_tailored_version: bool = False


class AutofixResponse(BaseModel):
    resume_id: uuid.UUID
    job_profile_id: uuid.UUID
    saved_resume_id: uuid.UUID | None = None
    result: AutofixResult
