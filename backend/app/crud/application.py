import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.application import Application
from app.schemas.application import ApplicationCreate, ApplicationStageUpdate, ApplicationUpdate


def _with_details(query):
    return query.options(
        selectinload(Application.company),
        selectinload(Application.job_profile),
        selectinload(Application.resume),
    )


async def create_application(session: AsyncSession, data: ApplicationCreate) -> Application:
    application = Application(**data.model_dump())
    session.add(application)
    await session.commit()
    await session.refresh(application)
    return application


async def list_applications(
    session: AsyncSession,
    user_id: uuid.UUID | None = None,
    stage: str | None = None,
    company_id: uuid.UUID | None = None,
) -> list[Application]:
    query = _with_details(select(Application))
    if user_id is not None:
        query = query.where(Application.user_id == user_id)
    if stage is not None:
        query = query.where(Application.stage == stage)
    if company_id is not None:
        query = query.where(Application.company_id == company_id)
    result = await session.exec(query)
    return list(result.all())


async def get_application(session: AsyncSession, application_id: uuid.UUID) -> Application | None:
    query = _with_details(select(Application).where(Application.id == application_id))
    result = await session.exec(query)
    return result.first()


async def update_application(
    session: AsyncSession, application: Application, data: ApplicationUpdate
) -> Application:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(application, field, value)
    application.updated_at = datetime.now(timezone.utc)
    session.add(application)
    await session.commit()
    await session.refresh(application)
    return application


async def update_application_stage(
    session: AsyncSession, application: Application, data: ApplicationStageUpdate
) -> Application:
    application.stage = data.stage
    application.board_position = data.board_position
    now = datetime.now(timezone.utc)
    application.stage_updated_at = now
    application.updated_at = now
    session.add(application)
    await session.commit()
    await session.refresh(application)
    return application


async def delete_application(session: AsyncSession, application: Application) -> None:
    await session.delete(application)
    await session.commit()
