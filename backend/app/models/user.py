import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime
from sqlmodel import Field, SQLModel

#: Two roles is all the moderation model needs. Kept as VARCHAR + CHECK rather
#: than a Postgres ENUM — widening a CHECK is a one-line migration, altering an
#: ENUM is not.
#: Three roles for user permissions: user, moderator, admin.
ROLES: tuple[str, ...] = ("user", "moderator", "admin")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ({})".format(", ".join(f"'{r}'" for r in ROLES)),
            name="ck_users_role",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    full_name: str = Field(max_length=255)
    email: str = Field(max_length=255, unique=True, index=True)
    #: Argon2id digest. Never leaves the model layer — no read schema exposes it.
    hashed_password: str = Field(max_length=255)
    role: str = Field(default="user", max_length=20, index=True)
    #: Deactivation is preferred over deletion: a user's resumes and moderation
    #: records reference them by FK, and a soft flag keeps that history intact.
    is_active: bool = Field(default=True)
    #: Bumped on password change and forced logout. Refresh tokens carry the
    #: version they were minted at, so raising this invalidates every
    #: outstanding session without a server-side session table.
    token_version: int = Field(default=0)
    current_title: str | None = Field(default=None, max_length=255)
    career_goals: str | None = Field(default=None)
    desired_salary_min: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    desired_salary_max: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    salary_currency: str = Field(default="USD", max_length=3)
    created_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=_utcnow, sa_type=DateTime(timezone=True))

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_moderator(self) -> bool:
        return self.role in ("moderator", "admin")
