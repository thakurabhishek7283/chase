from fastapi import APIRouter, status

from app.crud import technology as crud
from app.deps import SessionDep
from app.schemas.technology import TechnologyCreate, TechnologyRead

router = APIRouter(prefix="/technologies", tags=["technologies"])


@router.get("", response_model=list[TechnologyRead])
async def list_technologies(session: SessionDep) -> list[TechnologyRead]:
    return await crud.list_technologies(session)


@router.post("", response_model=TechnologyRead, status_code=status.HTTP_201_CREATED)
async def create_technology(data: TechnologyCreate, session: SessionDep) -> TechnologyRead:
    return await crud.create_technology(session, data)
