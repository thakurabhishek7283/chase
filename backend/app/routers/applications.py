import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.crud import application as crud
from app.deps import SessionDep
from app.schemas.application import (
    ApplicationCreate,
    ApplicationRead,
    ApplicationReadWithDetails,
    ApplicationStageUpdate,
    ApplicationUpdate,
)

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED)
async def create_application(data: ApplicationCreate, session: SessionDep) -> ApplicationRead:
    return await crud.create_application(session, data)


@router.get("", response_model=list[ApplicationReadWithDetails])
async def list_applications(
    session: SessionDep,
    user_id: uuid.UUID | None = Query(default=None),
    stage: str | None = Query(default=None),
    company_id: uuid.UUID | None = Query(default=None),
) -> list[ApplicationReadWithDetails]:
    return await crud.list_applications(session, user_id, stage, company_id)  # type: ignore[return-value]


@router.get("/{application_id}", response_model=ApplicationReadWithDetails)
async def get_application(application_id: uuid.UUID, session: SessionDep) -> ApplicationReadWithDetails:
    application = await crud.get_application(session, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return application  # type: ignore[return-value]


@router.patch("/{application_id}", response_model=ApplicationRead)
async def update_application(
    application_id: uuid.UUID, data: ApplicationUpdate, session: SessionDep
) -> ApplicationRead:
    application = await crud.get_application(session, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return await crud.update_application(session, application, data)


@router.patch("/{application_id}/stage", response_model=ApplicationRead)
async def update_application_stage(
    application_id: uuid.UUID, data: ApplicationStageUpdate, session: SessionDep
) -> ApplicationRead:
    application = await crud.get_application(session, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return await crud.update_application_stage(session, application, data)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(application_id: uuid.UUID, session: SessionDep) -> None:
    application = await crud.get_application(session, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    await crud.delete_application(session, application)
