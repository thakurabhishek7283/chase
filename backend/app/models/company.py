import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, Index, text
from sqlmodel import Field, SQLModel

from app.models.moderation import status_check, status_constraint_name


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Company(SQLModel, table=True):
    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint(
            "growth_trajectory IN ('declining', 'stable', 'growing', 'hypergrowth')",
            name="ck_companies_growth_trajectory",
        ),
        CheckConstraint(status_check("companies"), name=status_constraint_name("companies")),
        # Partial, excluding rejected rows. A plain UNIQUE would let one junk
        # submission squat a name forever: reject "Google" as nonsense and the
        # slug stays claimed, so the real Google can never be added — and the
        # next contributor gets a 409 pointing at a row they cannot even see.
        # Rejection has to release the name it was holding.
        Index(
            "uq_companies_slug_active",
            "slug",
            unique=True,
            postgresql_where=text("status <> 'rejected'"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    #: Display name. *Not* unique — "Acme, Inc." and "Acme Inc" are the same
    #: employer, and a unique index on the raw name happily admits both.
    #: Deduplication is `slug`'s job.
    name: str = Field(max_length=255, index=True)
    #: Normalised name (see services/slug.py): lowercased, punctuation and legal
    #: suffixes stripped. This is the real identity of a company row and the
    #: only thing standing between public data and a pile of near-duplicates.
    #: Uniqueness is enforced by `uq_companies_slug_active` above, which skips
    #: rejected rows — hence a plain index here rather than `unique=True`.
    slug: str = Field(max_length=255, index=True)
    industry: str | None = Field(default=None, max_length=255)
    growth_trajectory: str | None = Field(default=None, max_length=20)
    website: str | None = Field(default=None, max_length=255)

    # --- moderation ----------------------------------------------------------
    status: str = Field(default="pending", max_length=20, index=True)
    #: Nullable so rows that predate authentication (and any future importer)
    #: remain valid. A NULL contributor simply has no one to attribute it to.
    created_by: uuid.UUID | None = Field(default=None, foreign_key="users.id", index=True)
    reviewed_by: uuid.UUID | None = Field(default=None, foreign_key="users.id")
    reviewed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    rejection_reason: str | None = Field(default=None)

    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
