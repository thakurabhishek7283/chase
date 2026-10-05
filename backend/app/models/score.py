r"""One resume's ATS score against one job, kept so looking at it is free.

Scoring costs a model call. Looking at a score should not, and that difference is
the whole reason this table exists: the resume screen wants to open showing what
every document already scores, and a design where that costs one round trip per
version per role is a design nobody leaves open.

So a score is stored, and `content_hash` is what keeps it honest. It fingerprints
the document that was actually scored. A resume whose content or slot vocabulary
has moved on since still has its score — it is simply *stale*, which the API says
out loud rather than quietly serving a number about a document that no longer
exists. Staleness is a display fact, not an error: the old score is still the
last thing anyone knew, and hiding it would be worse than labelling it.

One row per (resume, job). Re-scoring overwrites in place rather than appending —
the history of what a document scored before it was edited is not something
anyone has asked to see, and keeping it would make the common read a sort.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ResumeScore(SQLModel, table=True):
    __tablename__ = "resume_scores"
    __table_args__ = (
        CheckConstraint(
            "match_score >= 0 AND match_score <= 100", name="ck_resume_scores_match_score"
        ),
        # The cache key. Also the reason the write path is an upsert rather than
        # an insert: a second scoring of the same pair replaces the first.
        Index("uq_resume_scores_resume_job", "resume_id", "job_profile_id", unique=True),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    #: Denormalised from the resume so ownership is one predicate, not a join.
    user_id: uuid.UUID = Field(
        sa_column=Column(
            Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    #: CASCADE both ways. Unlike a review — which is a record of work someone did
    #: and therefore holds a job profile hostage with RESTRICT — a score is a
    #: cached derivation. When either side goes, the number describes nothing.
    resume_id: uuid.UUID = Field(
        sa_column=Column(
            Uuid, ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    job_profile_id: uuid.UUID = Field(
        sa_column=Column(
            Uuid, ForeignKey("job_profiles.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )

    #: `document_fingerprint` of the resume at the moment it was scored. Compared
    #: against the resume's current fingerprint on every read to decide `stale`.
    content_hash: str = Field(max_length=32)

    match_score: int
    summary: str
    matched_keywords: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    missing_keywords: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )

    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
