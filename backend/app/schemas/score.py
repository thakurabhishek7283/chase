"""Wire types for a cached ATS score."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.ai.schemas import MissingKeyword


class ScoreRequest(BaseModel):
    """Score this resume against one job."""

    job_profile_id: uuid.UUID
    refresh: bool = Field(
        default=False,
        description=(
            "Score again even if the stored one still describes this document. "
            "A stale score is refreshed without asking; this is for the case "
            "where the job description itself has changed underneath it."
        ),
    )


class ScoreRead(BaseModel):
    """One resume's standing against one job, and whether it is still true."""

    id: uuid.UUID
    resume_id: uuid.UUID
    job_profile_id: uuid.UUID
    match_score: int
    summary: str
    matched_keywords: list[str]
    missing_keywords: list[MissingKeyword]
    #: The resume has changed since this was computed. The number is shown
    #: anyway — it is still the last thing anyone knew — but labelled.
    stale: bool
    #: False when the response came straight from the cache, so a client can
    #: tell "already knew this" from "just spent a model call finding out".
    computed: bool = False
    updated_at: datetime
