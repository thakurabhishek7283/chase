import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.job_profile import JobProfile
from app.models.user import User
from app.schemas.job_profile import JobProfileCreate, JobProfileUpdate


async def create_job_profile(
    session: AsyncSession, data: JobProfileCreate, *, author: User
) -> JobProfile:
    approved = author.is_admin
    now = datetime.now(timezone.utc)
    job_profile = JobProfile(
        **data.model_dump(),
        created_by=author.id,
        status="approved" if approved else "pending",
        reviewed_by=author.id if approved else None,
        reviewed_at=now if approved else None,
    )
    session.add(job_profile)
    await session.commit()
    await session.refresh(job_profile)
    return job_profile


async def find_duplicate(
    session: AsyncSession,
    *,
    company_id: uuid.UUID,
    external_job_id: str | None,
    position_title: str,
    location: str | None,
) -> JobProfile | None:
    """Locate an existing posting under the same identity rule as the indexes.

    This mirrors `uq_job_profiles_company_external_id` and
    `uq_job_profiles_company_title_location` in `models/job_profile.py`. The
    query exists to produce a helpful 409 body pointing at the row that already
    covers this posting; the indexes are what actually guarantee uniqueness
    under concurrency, so the two must be changed together.
    """
    if external_job_id:
        query = select(JobProfile).where(
            JobProfile.company_id == company_id,
            JobProfile.external_job_id == external_job_id,
        )
    else:
        query = select(JobProfile).where(
            JobProfile.company_id == company_id,
            col(JobProfile.external_job_id).is_(None),
            func.lower(col(JobProfile.position_title)) == position_title.strip().lower(),
            func.lower(func.coalesce(col(JobProfile.location), ""))
            == (location or "").strip().lower(),
        )
    # Rejected postings do not hold their key — see `find_by_slug`.
    result = await session.exec(query.where(JobProfile.status != "rejected"))
    return result.first()


async def count_pending_for(session: AsyncSession, user_id: uuid.UUID) -> int:
    result = await session.exec(
        select(func.count())
        .select_from(JobProfile)
        .where(JobProfile.created_by == user_id, JobProfile.status == "pending")
    )
    return int(result.one())


async def purge_rejected(session: AsyncSession, older_than: datetime) -> int:
    """Delete rejected postings reviewed before `older_than`."""
    rows = (
        await session.exec(
            select(JobProfile).where(
                JobProfile.status == "rejected", col(JobProfile.reviewed_at) < older_than
            )
        )
    ).all()
    for row in rows:
        await session.delete(row)
    await session.commit()
    return len(rows)


async def list_job_profiles(
    session: AsyncSession,
    scope: ColumnElement[bool],
    *,
    company_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[JobProfile]:
    query = select(JobProfile).where(scope)
    if company_id is not None:
        query = query.where(JobProfile.company_id == company_id)
    if status is not None:
        query = query.where(JobProfile.status == status)
    result = await session.exec(query.order_by(col(JobProfile.created_at).desc()))
    return list(result.all())


async def get_job_profile(session: AsyncSession, job_profile_id: uuid.UUID) -> JobProfile | None:
    return await session.get(JobProfile, job_profile_id)


async def update_job_profile(
    session: AsyncSession, job_profile: JobProfile, data: JobProfileUpdate
) -> JobProfile:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(job_profile, field, value)
    job_profile.updated_at = datetime.now(timezone.utc)
    session.add(job_profile)
    await session.commit()
    await session.refresh(job_profile)
    return job_profile


async def set_moderation_status(
    session: AsyncSession,
    job_profile: JobProfile,
    *,
    status: str,
    reviewer: User,
    reason: str | None = None,
) -> JobProfile:
    job_profile.status = status
    job_profile.reviewed_by = reviewer.id
    job_profile.reviewed_at = datetime.now(timezone.utc)
    job_profile.rejection_reason = reason
    job_profile.updated_at = job_profile.reviewed_at
    session.add(job_profile)
    await session.commit()
    await session.refresh(job_profile)
    return job_profile


async def delete_job_profile(session: AsyncSession, job_profile: JobProfile) -> None:
    await session.delete(job_profile)
    await session.commit()
