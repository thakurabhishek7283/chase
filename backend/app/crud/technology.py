from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.technology import Technology
from app.schemas.technology import TechnologyCreate


async def list_technologies(session: AsyncSession) -> list[Technology]:
    result = await session.exec(select(Technology))
    return list(result.all())


async def create_technology(session: AsyncSession, data: TechnologyCreate) -> Technology:
    technology = Technology(**data.model_dump())
    session.add(technology)
    await session.commit()
    await session.refresh(technology)
    return technology


async def get_or_create_technology_by_name(
    session: AsyncSession, name: str, category: str | None = None
) -> Technology:
    result = await session.exec(select(Technology).where(Technology.name == name))
    existing = result.first()
    if existing is not None:
        return existing
    technology = Technology(name=name, category=category)
    session.add(technology)
    await session.commit()
    await session.refresh(technology)
    return technology
