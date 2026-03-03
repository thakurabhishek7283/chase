import uuid
from datetime import datetime, timezone

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crud.technology import get_or_create_technology_by_name
from app.models.company import Company
from app.models.technology import CompanyTechnology, Technology
from app.schemas.company import CompanyCreate, CompanyUpdate


async def create_company(session: AsyncSession, data: CompanyCreate) -> Company:
    company = Company(**data.model_dump())
    session.add(company)
    await session.commit()
    await session.refresh(company)
    return company


async def list_companies(session: AsyncSession) -> list[Company]:
    result = await session.exec(select(Company))
    return list(result.all())


async def get_company(session: AsyncSession, company_id: uuid.UUID) -> Company | None:
    return await session.get(Company, company_id)


async def update_company(session: AsyncSession, company: Company, data: CompanyUpdate) -> Company:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(company, field, value)
    company.updated_at = datetime.now(timezone.utc)
    session.add(company)
    await session.commit()
    await session.refresh(company)
    return company


async def delete_company(session: AsyncSession, company: Company) -> None:
    await session.delete(company)
    await session.commit()


async def list_company_technologies(session: AsyncSession, company_id: uuid.UUID) -> list[Technology]:
    result = await session.exec(
        select(Technology)
        .join(CompanyTechnology, CompanyTechnology.technology_id == Technology.id)
        .where(CompanyTechnology.company_id == company_id)
    )
    return list(result.all())


async def attach_company_technology(
    session: AsyncSession, company_id: uuid.UUID, technology_name: str, category: str | None
) -> Technology:
    technology = await get_or_create_technology_by_name(session, technology_name, category)
    existing = await session.get(CompanyTechnology, (company_id, technology.id))
    if existing is None:
        session.add(CompanyTechnology(company_id=company_id, technology_id=technology.id))
        await session.commit()
    return technology


async def detach_company_technology(
    session: AsyncSession, company_id: uuid.UUID, technology_id: uuid.UUID
) -> None:
    link = await session.get(CompanyTechnology, (company_id, technology_id))
    if link is not None:
        await session.delete(link)
        await session.commit()
