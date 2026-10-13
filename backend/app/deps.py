"""Dependency-injection seams: the database session, the current user, and the
authorization policies built on top of them.

This module is allowed to raise `HTTPException` — it exists to translate
request context into either a permitted operation or an HTTP error, which is a
router concern. `app/services/` remains bound by the opposite rule and raises
domain errors only.

**The two scope rules, in one place:**

*Private data* (resumes) is reachable only by its owner. A non-owner gets
**404, not 403**, so the API never confirms that someone else's resume id
exists.

*Public data* (companies, job profiles) is community-contributed and
admin-moderated. Everyone sees `approved` rows; a contributor additionally sees
their own `pending` and `rejected` ones, so proposing a company does not block
the work that motivated it while an admin catches up.
"""

import uuid
from typing import Annotated, TypeVar

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import true
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import or_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.security import TokenError, decode_token, subject_of
from app.models.company import Company
from app.models.job_profile import JobProfile
from app.models.resume import Resume
from app.models.user import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]

#: `auto_error=False` so a missing header produces our own 401 with a useful
#: message rather than FastAPI's bare "Not authenticated".
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/token", auto_error=False)

TokenDep = Annotated[str | None, Depends(oauth2_scheme)]

#: Moderated public tables share a shape; the helpers below are generic over it.
Moderated = TypeVar("Moderated", Company, JobProfile)

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="This endpoint requires a bearer token. Sign in at /api/v1/auth/login.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(session: SessionDep, token: TokenDep) -> User:
    if token is None:
        raise _UNAUTHENTICATED
    try:
        payload = decode_token(token, "access")
        user_id = subject_of(payload)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        # A token for a deleted or deactivated account is no better than a
        # forged one, and saying which it is leaks account existence.
        raise _UNAUTHENTICATED

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action is restricted to administrators.",
        )
    return user


AdminUser = Annotated[User, Depends(get_current_admin)]


async def get_current_moderator(user: CurrentUser) -> User:
    if not user.is_moderator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action is restricted to moderators and administrators.",
        )
    return user


ModeratorUser = Annotated[User, Depends(get_current_moderator)]


# --- private, owned data -----------------------------------------------------


def require_self_or_admin(target_user_id: uuid.UUID, user: User) -> None:
    """Guard endpoints addressed by a user id in the path."""
    if user.id != target_user_id and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )


async def require_owned_resume(
    session: AsyncSession, resume_id: uuid.UUID, user: User
) -> Resume:
    """Load a resume the caller owns. There is no role that bypasses this.

    Not even admins — deliberately, and this is the one authorization rule in
    the app with no administrative override. Moderation is about *public* data;
    no administrative task requires reading someone's resume, so there is no
    path through the API that lets one be read by anybody but its owner.
    """
    resume = await session.get(Resume, resume_id)
    if resume is None or resume.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    return resume


# --- public, moderated data --------------------------------------------------


def visible_scope(model: type[Moderated], user: User) -> ColumnElement[bool]:
    """The WHERE clause restricting a moderated table to what `user` may see.

    Returned as a predicate rather than applied inline so the callers in
    `crud/` stay ordinary queries, and so this rule exists in exactly one place
    — `is_visible` below is its row-level twin and the two must agree.
    """
    if user.is_moderator:
        return true()
    return or_(
        model.status == "approved",  # type: ignore[arg-type]
        model.created_by == user.id,  # type: ignore[arg-type]
    )


def is_visible(row: Company | JobProfile, user: User) -> bool:
    """Row-level counterpart of `visible_scope`, for already-loaded objects."""
    return user.is_moderator or row.status == "approved" or row.created_by == user.id


def can_edit(row: Company | JobProfile, user: User) -> bool:
    """Who may amend a moderated row.

    Admins and moderators always or while pending for contributor.
    """
    return user.is_moderator or (row.status == "pending" and row.created_by == user.id)


async def require_visible_company(
    session: AsyncSession, company_id: uuid.UUID, user: User
) -> Company:
    company = await session.get(Company, company_id)
    if company is None or not is_visible(company, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return company


async def require_visible_job_profile(
    session: AsyncSession, job_profile_id: uuid.UUID, user: User
) -> JobProfile:
    job = await session.get(JobProfile, job_profile_id)
    if job is None or not is_visible(job, user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job profile not found"
        )
    return job


def require_submission_quota(pending: int, user: User, noun: str) -> None:
    """Cap how much unreviewed data one account can put in the shared tables.

    Moderation decides whether a submission is *good*; it does nothing about
    *volume*, and a pending row is a real row in the real table however well
    hidden it is from other users. Without a ceiling, one account can insert
    thousands of entries faster than any admin can review them.

    Admins are exempt because their submissions are approved on creation and so
    are never pending in the first place.
    """
    if user.is_admin:
        return
    limit = get_settings().max_pending_submissions_per_user
    if pending >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"You already have {pending} {noun} submissions awaiting review, which is "
                f"the limit of {limit}. Wait for those to be reviewed before adding more."
            ),
        )


def require_editable(row: Company | JobProfile, user: User, noun: str) -> None:
    if not can_edit(row, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"This {noun} has been approved as shared public data. "
                "Ask an administrator to amend it."
            ),
        )


# --- optional dependencies ---------------------------------------------------


def require_llm_key() -> None:
    """Fail fast with a clear message rather than a provider stack trace."""
    from app.ai.provider import has_llm_credentials, llm_credentials_hint

    if not has_llm_credentials():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=llm_credentials_hint(),
        )
