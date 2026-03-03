import uuid
from datetime import datetime, timezone

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crud.technology import get_or_create_technology_by_name
from app.models.job_profile import JobProfile
from app.models.technology import JobProfileTechnology, Technology
from app.schemas.job_profile import JobProfileCreate, JobProfileUpdate


async def create_job_profile(session: AsyncSession, data: JobProfileCreate) -> JobProfile:
    job_profile = JobProfile(**data.model_dump())
    session.add(job_profile)
    await session.commit()
    await session.refresh(job_profile)
    return job_profile


async def list_job_profiles(
    session: AsyncSession, company_id: uuid.UUID | None = None
) -> list[JobProfile]:
    query = select(JobProfile)
    if company_id is not None:
        query = query.where(JobProfile.company_id == company_id)
    result = await session.exec(query)
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


async def delete_job_profile(session: AsyncSession, job_profile: JobProfile) -> None:
    await session.delete(job_profile)
    await session.commit()


async def list_job_profile_technologies(
    session: AsyncSession, job_profile_id: uuid.UUID
) -> list[Technology]:
    result = await session.exec(
        select(Technology)
        .join(JobProfileTechnology, JobProfileTechnology.technology_id == Technology.id)
        .where(JobProfileTechnology.job_profile_id == job_profile_id)
    )
    return list(result.all())


async def attach_job_profile_technology(
    session: AsyncSession,
    job_profile_id: uuid.UUID,
    technology_name: str,
    category: str | None,
    requirement_level: str,
) -> Technology:
    technology = await get_or_create_technology_by_name(session, technology_name, category)
    existing = await session.get(JobProfileTechnology, (job_profile_id, technology.id))
    if existing is None:
        session.add(
            JobProfileTechnology(
                job_profile_id=job_profile_id,
                technology_id=technology.id,
                requirement_level=requirement_level,
            )
        )
        await session.commit()
    return technology


async def detach_job_profile_technology(
    session: AsyncSession, job_profile_id: uuid.UUID, technology_id: uuid.UUID
) -> None:
    link = await session.get(JobProfileTechnology, (job_profile_id, technology_id))
    if link is not None:
        await session.delete(link)
        await session.commit()
