import uuid

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.resume import Resume


async def list_resumes(session: AsyncSession, user_id: uuid.UUID) -> list[Resume]:
    """Every resume belonging to one user, masters before their children.

    `user_id` is required rather than optional: an omitted filter used to mean
    "all resumes from every account", which is not a query this API should be
    able to express.
    """
    result = await session.exec(
        select(Resume)
        .where(Resume.user_id == user_id)
        .order_by(col(Resume.master_resume_id).nulls_first(), col(Resume.created_at))
    )
    return list(result.all())


async def get_resume(session: AsyncSession, resume_id: uuid.UUID) -> Resume | None:
    return await session.get(Resume, resume_id)


async def list_resume_versions(
    session: AsyncSession, master_resume_id: uuid.UUID, *, user_id: uuid.UUID
) -> list[Resume]:
    result = await session.exec(
        select(Resume).where(
            Resume.master_resume_id == master_resume_id, Resume.user_id == user_id
        )
    )
    return list(result.all())


async def delete_resume(session: AsyncSession, resume: Resume) -> None:
    """Delete a resume, and its tailored children if it is a master.

    The children go first and explicitly. `resumes.master_resume_id` is a
    self-referential FK with no cascade — adding one would mean a self-cascading
    delete, which Postgres allows but which makes "delete this row" a recursive
    operation that is easy to trigger by accident. Doing it here keeps the blast
    radius visible at the call site.

    Reviews of this master *do* cascade at the database level; a review of a
    document that no longer exists could never be finalized.
    """
    children = await session.exec(select(Resume).where(Resume.master_resume_id == resume.id))
    for child in children.all():
        await session.delete(child)
    # Flushed before the parent goes. Both deletes in one flush would be ordered
    # by SQLAlchemy's own dependency sort, which knows nothing about a
    # self-referential FK declared only as a column — so the parent can go first
    # and Postgres rejects the whole statement.
    await session.flush()
    await session.delete(resume)
    await session.commit()
