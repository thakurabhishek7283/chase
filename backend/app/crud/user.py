import uuid
from datetime import datetime, timezone
from typing import Any

from sqlmodel import SQLModel, col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.company import Company
from app.models.job_profile import JobProfile
from app.models.resume import Resume
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate


def normalize_email(email: str) -> str:
    """Emails are matched case-insensitively, so they are stored folded.

    Without this, `Ada@example.com` and `ada@example.com` are two accounts as
    far as the unique index is concerned, and a user who capitalises
    inconsistently gets "invalid credentials" on a correct password.
    """
    return email.strip().lower()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.exec(select(User).where(User.email == normalize_email(email)))
    return result.first()


async def create_user(
    session: AsyncSession, data: UserCreate, *, role: str | None = None
) -> User:
    """Create an account, resolving its role from configuration if not given."""
    email = normalize_email(data.email)
    payload = data.model_dump(exclude={"password", "email", "role"})
    assigned_role = role or data.role or _initial_role(email)
    user = User(
        **payload,
        email=email,
        hashed_password=hash_password(data.password),
        role=assigned_role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


def _initial_role(email: str) -> str:
    """Admin only for the configured bootstrap address.

    The obvious alternative — "the first account to register becomes admin" —
    races on a publicly reachable instance: whoever reaches the endpoint first
    owns the moderation queue, and there is no way to tell that it happened.
    """
    configured = get_settings().bootstrap_admin_email
    if configured and normalize_email(configured) == email:
        return "admin"
    return "user"


async def count_users(session: AsyncSession) -> int:
    result = await session.exec(select(func.count()).select_from(User))
    return int(result.one())


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.exec(select(User).order_by(col(User.created_at)))
    return list(result.all())


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def update_user(session: AsyncSession, user: User, data: UserUpdate) -> User:
    fields = data.model_dump(exclude_unset=True)
    if "email" in fields and fields["email"] is not None:
        fields["email"] = normalize_email(fields["email"])
    for field, value in fields.items():
        setattr(user, field, value)
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def set_password(session: AsyncSession, user: User, new_password: str) -> User:
    """Change a password and invalidate every outstanding session.

    Bumping `token_version` is the point: a password change that left old
    refresh tokens working would not actually evict whoever prompted it.
    """
    user.hashed_password = hash_password(new_password)
    user.token_version += 1
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def set_role(session: AsyncSession, user: User, role: str) -> User:
    user.role = role
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def set_active(session: AsyncSession, user: User, is_active: bool) -> User:
    user.is_active = is_active
    # Deactivation must also cut existing sessions, or the account stays usable
    # until its refresh token happens to expire.
    if not is_active:
        user.token_version += 1
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def count_admins(session: AsyncSession) -> int:
    result = await session.exec(
        select(func.count()).select_from(User).where(User.role == "admin", User.is_active)
    )
    return int(result.one())


#: Every column that points at `users.id` with a plain (RESTRICT) foreign key,
#: labelled for the message an admin reads. `refresh_tokens` cascades and
#: `audit_logs` nulls out, so neither belongs here — these are precisely the
#: references that make a delete fail, and the list has to be kept in step with
#: the models when a new one is added.
_BLOCKING_REFERENCES: tuple[tuple[str, type[SQLModel], Any], ...] = (
    ("resume", Resume, Resume.user_id),
    ("submitted company", Company, Company.created_by),
    ("reviewed company", Company, Company.reviewed_by),
    ("submitted job profile", JobProfile, JobProfile.created_by),
    ("reviewed job profile", JobProfile, JobProfile.reviewed_by),
)


async def count_blocking_references(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[str, int]:
    """Count the rows that would make `delete_user` fail, keyed by label.

    An empty mapping means the account can be hard-deleted. Anything else is
    the explanation the caller owes the admin: the alternative is letting the
    FK violation surface from `commit()` as a 500 with the constraint name in
    it, which tells them nothing they can act on.
    """
    counts: dict[str, int] = {}
    for label, model, column in _BLOCKING_REFERENCES:
        result = await session.exec(
            select(func.count()).select_from(model).where(col(column) == user_id)
        )
        found = int(result.one())
        if found:
            counts[label] = counts.get(label, 0) + found
    return counts


async def delete_user(session: AsyncSession, user: User) -> None:
    await session.delete(user)
    await session.commit()
