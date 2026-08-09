import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

ExperienceTier = Literal[
    "intern", "junior", "mid", "senior", "staff", "principal", "executive"
]
ModerationStatus = Literal["pending", "approved", "rejected"]

_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)

#: A description this short cannot be a real posting, and — more to the point —
#: cannot be scored against a resume. The ATS agent needs requirements to work
#: from, so a two-word "description" produces a confident, meaningless score.
MIN_DESCRIPTION_LENGTH = 40


def _check_title(value: str) -> str:
    title = " ".join(value.split())
    if len(title) < 2:
        raise ValueError("A position title needs at least two characters.")
    if not _HAS_LETTER.search(title):
        raise ValueError("A position title must contain at least one letter.")
    return title


def _check_description(value: str) -> str:
    description = value.strip()
    if len(description) < MIN_DESCRIPTION_LENGTH:
        raise ValueError(
            f"Paste the actual job description — at least {MIN_DESCRIPTION_LENGTH} "
            "characters. It is what ATS scoring and matching read."
        )
    return description


def _check_job_id(value: str | None) -> str | None:
    if value is None or not value.strip():
        # Normalise "" to None so it lands in the title+location index rather
        # than becoming a distinct empty-string key.
        return None
    return value.strip()


JobTitle = Annotated[str, AfterValidator(_check_title)]
JobDescription = Annotated[str, AfterValidator(_check_description)]
ExternalJobId = Annotated[str | None, AfterValidator(_check_job_id)]


class JobProfileCreate(BaseModel):
    company_id: uuid.UUID
    #: The employer's own requisition id. Optional, because plenty of postings
    #: never show one — see the composite key in `models/job_profile.py` for
    #: what identifies a posting in that case.
    external_job_id: ExternalJobId = Field(default=None, max_length=128)
    position_title: JobTitle = Field(max_length=255)
    experience_tier: ExperienceTier | None = None
    description: JobDescription
    location: str | None = Field(default=None, max_length=255)
    employment_type: str | None = Field(default=None, max_length=50)


class JobProfileUpdate(BaseModel):
    external_job_id: ExternalJobId = Field(default=None, max_length=128)
    position_title: JobTitle | None = Field(default=None, max_length=255)
    experience_tier: ExperienceTier | None = None
    description: JobDescription | None = None
    location: str | None = Field(default=None, max_length=255)
    employment_type: str | None = Field(default=None, max_length=50)


class JobProfileReject(BaseModel):
    reason: str = Field(min_length=1)


class JobProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    external_job_id: str | None
    position_title: str
    experience_tier: str | None
    description: str
    location: str | None
    employment_type: str | None
    status: str
    created_by: uuid.UUID | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime


class DuplicateJobProfile(BaseModel):
    detail: str
    existing: JobProfileRead
