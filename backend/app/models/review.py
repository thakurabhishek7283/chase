r"""A reviewed tailoring: one resume, one job, and every proposed change to it.

The model proposes all its edits in a single pass, and the author then works
through them one at a time. That review has to outlive the request — a patch can
be sent back for revision, which is another round trip, and the rule that *no
child resume exists until every patch is resolved* is only enforceable if the
server knows which ones are still outstanding. So it is a table, not a draft the
client carries.

Two details are load-bearing:

**`base_hashes`** freezes the source resume's slot fingerprints at the moment the
review was created. Splicing happens at finalize, possibly much later, against a
document that may have been re-uploaded or had its slot config changed. Replaying
the hashes turns "silently spliced into the wrong bullet list" into a 409.

**`initial_*` alongside `proposed_*`** keeps the model's first answer after a
feedback revision overwrites the proposal, so the author can always get back to
what they were originally offered.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

#: A review is `open` until it is finalized; finalizing writes the child resume
#: and closes it. There is no `abandoned` — deleting the row says that.
ReviewStatus = ("open", "finalized")
#: `pending` is the only status that blocks preview and finalize.
PatchStatus = ("pending", "accepted", "rejected")
#: Which half of `services/latex/model.py` this patch addresses.
SlotKind = ("group", "region")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResumeReview(SQLModel, table=True):
    __tablename__ = "resume_reviews"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'finalized')", name="ck_resume_reviews_status"),
        CheckConstraint(
            "match_score >= 0 AND match_score <= 100", name="ck_resume_reviews_match_score"
        ),
        # The detail screen lists one resume's reviews newest-first.
        Index("ix_resume_reviews_source_created", "source_resume_id", "created_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    #: Denormalised from the master so ownership is one predicate, not a join.
    user_id: uuid.UUID = Field(
        sa_column=Column(
            Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    #: The document that was reviewed — a master, or one of its tailored
    #: children being taken another round. Not necessarily the resume the child
    #: this review produces will hang off: the tree stays one level deep, so a
    #: child's review finalizes into a *sibling*, not a grandchild.
    #:
    #: Deleting the reviewed document takes its reviews with it — a review of a
    #: resume that no longer exists cannot be finalized or even displayed.
    source_resume_id: uuid.UUID = Field(
        sa_column=Column(
            Uuid, ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    #: RESTRICT rather than CASCADE: a job profile is shared, moderated data, and
    #: rejecting one should not silently destroy someone's in-progress review.
    job_profile_id: uuid.UUID = Field(
        sa_column=Column(
            Uuid, ForeignKey("job_profiles.id", ondelete="RESTRICT"), nullable=False, index=True
        )
    )
    status: str = Field(default="open", max_length=16)

    match_score: int
    summary: str
    matched_keywords: list[str] = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    missing_keywords: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )

    #: Slot id -> fingerprint, captured from `slot_hashes(master)` at creation.
    base_hashes: dict[str, str] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    #: Set once, at finalize. SET NULL rather than CASCADE: deleting the child
    #: should not erase the record that this review produced one.
    child_resume_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(Uuid, ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True),
    )

    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))


class ResumePatch(SQLModel, table=True):
    __tablename__ = "resume_patches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')", name="ck_resume_patches_status"
        ),
        CheckConstraint("slot_kind IN ('group', 'region')", name="ck_resume_patches_slot_kind"),
        # A group patch carries item lists and a region patch carries LaTeX;
        # neither may carry the other's shape. Without this a `slot_kind` typo
        # becomes a patch that silently splices nothing.
        CheckConstraint(
            "(slot_kind = 'group' AND proposed_items IS NOT NULL AND proposed_latex IS NULL)"
            " OR (slot_kind = 'region' AND proposed_latex IS NOT NULL AND proposed_items IS NULL)",
            name="ck_resume_patches_payload_matches_kind",
        ),
        # One proposal per slot per review — the model returning `g2` twice is a
        # bug, and letting both through would splice one and drop the other.
        Index("uq_resume_patches_review_slot", "review_id", "slot_id", unique=True),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    review_id: uuid.UUID = Field(
        sa_column=Column(
            Uuid, ForeignKey("resume_reviews.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    #: The parser's id for this slot — `g2`, `r1`. Meaningful only against the
    #: source resume parsed with the config it had when the review was created,
    #: which is what `base_hashes` exists to prove.
    slot_id: str = Field(max_length=32)
    slot_kind: str = Field(max_length=8)
    #: Denormalised for display. The patch list has to read as a document to the
    #: author, and re-parsing the source to find one heading is wasteful.
    section_heading: str = Field(default="", max_length=255)

    # `none_as_null` matters here, and is not a style choice. Without it
    # SQLAlchemy stores Python `None` as the JSON value `null`, which is not SQL
    # NULL — so `proposed_items IS NULL` is false for a region patch and the
    # payload CHECK above rejects every row it was written to allow.
    original_items: list[str] | None = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True)
    )
    original_latex: str | None = Field(default=None)
    proposed_items: list[str] | None = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True)
    )
    proposed_latex: str | None = Field(default=None)
    #: The model's first answer, before any feedback revision.
    initial_items: list[str] | None = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True)
    )
    initial_latex: str | None = Field(default=None)

    reason: str = Field(default="")
    severity: str = Field(default="important", max_length=16)
    status: str = Field(default="pending", max_length=16)
    #: The author's most recent note, kept so the screen can show what they asked
    #: for next to what came back.
    feedback: str | None = Field(default=None)
    revision_count: int = Field(default=0)

    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))

    @property
    def is_group(self) -> bool:
        return self.slot_kind == "group"
