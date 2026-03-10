import uuid

from fastapi import APIRouter, HTTPException, status

from app.crud import company as crud
from app.deps import SessionDep
from app.schemas.company import (
    CompanyCreate,
    CompanyRead,
    CompanyReadWithTechnologies,
    CompanyUpdate,
)
from app.schemas.technology import CompanyTechnologyAttach, TechnologyRead

router = APIRouter(prefix="/companies", tags=["companies"])


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create_company(data: CompanyCreate, session: SessionDep) -> CompanyRead:
    return await crud.create_company(session, data)


@router.get("", response_model=list[CompanyRead])
async def list_companies(session: SessionDep) -> list[CompanyRead]:
    return await crud.list_companies(session)


@router.get("/{company_id}", response_model=CompanyReadWithTechnologies)
async def get_company(company_id: uuid.UUID, session: SessionDep) -> CompanyReadWithTechnologies:
    company = await crud.get_company(session, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    technologies = await crud.list_company_technologies(session, company_id)
    return CompanyReadWithTechnologies(**company.model_dump(), technologies=technologies)


@router.patch("/{company_id}", response_model=CompanyRead)
async def update_company(company_id: uuid.UUID, data: CompanyUpdate, session: SessionDep) -> CompanyRead:
    company = await crud.get_company(session, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return await crud.update_company(session, company, data)


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(company_id: uuid.UUID, session: SessionDep) -> None:
    company = await crud.get_company(session, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    await crud.delete_company(session, company)


@router.post("/{company_id}/technologies", response_model=TechnologyRead, status_code=status.HTTP_201_CREATED)
async def attach_company_technology(
    company_id: uuid.UUID, data: CompanyTechnologyAttach, session: SessionDep
) -> TechnologyRead:
    company = await crud.get_company(session, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return await crud.attach_company_technology(session, company_id, data.technology_name, data.category)


@router.delete("/{company_id}/technologies/{technology_id}", status_code=status.HTTP_204_NO_CONTENT)
async def detach_company_technology(
    company_id: uuid.UUID, technology_id: uuid.UUID, session: SessionDep
) -> None:
    await crud.detach_company_technology(session, company_id, technology_id)
