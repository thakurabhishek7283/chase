"""Wire types for a reviewed tailoring."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas import MissingKeyword


class ReviewCreate(BaseModel):
    """Score a resume against one job and propose every change, in one pass.

    The resume may be a master or one of its tailored versions; reviewing a
    version is how its ATS score gets improved rather than merely reported.
    """

    job_profile_id: uuid.UUID


class PatchDecision(BaseModel):
    """Accept or reject one proposal. Costs nothing — no model is involved."""

    action: Literal["accept", "reject"]


class PatchFeedback(BaseModel):
    """Send one proposal back for another attempt, with a brief."""

    feedback: str = Field(
        min_length=3,
        max_length=2000,
        description="What is wrong with the proposal and what it should say instead.",
    )


class PatchRead(BaseModel):
    """One proposed slot change, and where the author has got to with it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slot_id: str
    slot_kind: str
    section_heading: str
    #: What the reviewed resume says today. The screen shows it beside the
    #: a patch is unjudgeable without the text it would replace.
    original_items: list[str] | None
    original_latex: str | None
    proposed_items: list[str] | None
    proposed_latex: str | None
    reason: str
    severity: str
    status: str
    feedback: str | None
    #: How many times this one has been sent back. Shown so a patch that has
    #: been round the loop three times reads as the problem it is.
    revision_count: int


class ReviewRead(BaseModel):
    """A review and every patch in it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    #: The resume this was reviewed against. Not necessarily where
    #: `child_resume_id` ends up hanging — that is always the root master.
    source_resume_id: uuid.UUID
    job_profile_id: uuid.UUID
    status: str
    #: The source resume's own ATS standing, before any of these patches.
    match_score: int
    summary: str
    matched_keywords: list[str]
    missing_keywords: list[MissingKeyword]
    child_resume_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    patches: list[PatchRead] = Field(default_factory=list)
    #: Zero is the gate: preview and finalize both refuse until it is.
    pending_count: int = 0


class ReviewSummary(BaseModel):
    """A review without its patches, for the list on the resume screen."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_profile_id: uuid.UUID
    status: str
    match_score: int
    child_resume_id: uuid.UUID | None
    created_at: datetime
    pending_count: int = 0


class FinalizeRequest(BaseModel):
    version_label: str | None = Field(
        default=None, max_length=100, description="Defaults to 'Tailored for <role>'."
    )


class FinalizeResponse(BaseModel):
    review_id: uuid.UUID
    child_resume_id: uuid.UUID
    title: str
    version_label: str | None = None
    #: How many of the proposals actually made it into the document.
    accepted_count: int
    rejected_count: int
