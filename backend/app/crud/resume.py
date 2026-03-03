import uuid
from datetime import datetime, timezone

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.resume import Resume
from app.schemas.resume import ResumeCreate, ResumeUpdate


async def create_resume(session: AsyncSession, data: ResumeCreate) -> Resume:
    resume = Resume(**data.model_dump())
    session.add(resume)
    await session.commit()
    await session.refresh(resume)
    return resume


async def list_resumes(
    session: AsyncSession, user_id: uuid.UUID | None = None, master_only: bool = False
) -> list[Resume]:
    query = select(Resume)
    if user_id is not None:
        query = query.where(Resume.user_id == user_id)
    if master_only:
        query = query.where(Resume.master_resume_id.is_(None))  # type: ignore[union-attr]
    result = await session.exec(query)
    return list(result.all())


async def get_resume(session: AsyncSession, resume_id: uuid.UUID) -> Resume | None:
    return await session.get(Resume, resume_id)


async def list_resume_versions(session: AsyncSession, master_resume_id: uuid.UUID) -> list[Resume]:
    result = await session.exec(select(Resume).where(Resume.master_resume_id == master_resume_id))
    return list(result.all())


async def update_resume(session: AsyncSession, resume: Resume, data: ResumeUpdate) -> Resume:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(resume, field, value)
    resume.updated_at = datetime.now(timezone.utc)
    session.add(resume)
    await session.commit()
    await session.refresh(resume)
    return resume


async def delete_resume(session: AsyncSession, resume: Resume) -> None:
    await session.delete(resume)
    await session.commit()
