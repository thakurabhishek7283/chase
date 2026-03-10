import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.crud import job_profile as crud
from app.deps import SessionDep
from app.schemas.job_profile import (
    JobProfileCreate,
    JobProfileRead,
    JobProfileReadWithTechnologies,
    JobProfileUpdate,
)
from app.schemas.technology import JobProfileTechnologyAttach, TechnologyRead

router = APIRouter(prefix="/job-profiles", tags=["job-profiles"])


@router.post("", response_model=JobProfileRead, status_code=status.HTTP_201_CREATED)
async def create_job_profile(data: JobProfileCreate, session: SessionDep) -> JobProfileRead:
    return await crud.create_job_profile(session, data)


@router.get("", response_model=list[JobProfileRead])
async def list_job_profiles(
    session: SessionDep, company_id: uuid.UUID | None = Query(default=None)
) -> list[JobProfileRead]:
    return await crud.list_job_profiles(session, company_id)


@router.get("/{job_profile_id}", response_model=JobProfileReadWithTechnologies)
async def get_job_profile(
    job_profile_id: uuid.UUID, session: SessionDep
) -> JobProfileReadWithTechnologies:
    job_profile = await crud.get_job_profile(session, job_profile_id)
    if job_profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job profile not found")
    technologies = await crud.list_job_profile_technologies(session, job_profile_id)
    return JobProfileReadWithTechnologies(**job_profile.model_dump(), technologies=technologies)


@router.patch("/{job_profile_id}", response_model=JobProfileRead)
async def update_job_profile(
    job_profile_id: uuid.UUID, data: JobProfileUpdate, session: SessionDep
) -> JobProfileRead:
    job_profile = await crud.get_job_profile(session, job_profile_id)
    if job_profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job profile not found")
    return await crud.update_job_profile(session, job_profile, data)


@router.delete("/{job_profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job_profile(job_profile_id: uuid.UUID, session: SessionDep) -> None:
    job_profile = await crud.get_job_profile(session, job_profile_id)
    if job_profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job profile not found")
    await crud.delete_job_profile(session, job_profile)


@router.post(
    "/{job_profile_id}/technologies",
    response_model=TechnologyRead,
    status_code=status.HTTP_201_CREATED,
)
async def attach_job_profile_technology(
    job_profile_id: uuid.UUID, data: JobProfileTechnologyAttach, session: SessionDep
) -> TechnologyRead:
    job_profile = await crud.get_job_profile(session, job_profile_id)
    if job_profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job profile not found")
    return await crud.attach_job_profile_technology(
        session, job_profile_id, data.technology_name, data.category, data.requirement_level
    )


@router.delete(
    "/{job_profile_id}/technologies/{technology_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def detach_job_profile_technology(
    job_profile_id: uuid.UUID, technology_id: uuid.UUID, session: SessionDep
) -> None:
    await crud.detach_job_profile_technology(session, job_profile_id, technology_id)
