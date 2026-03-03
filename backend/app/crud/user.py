import uuid
from datetime import datetime, timezone

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate


async def create_user(session: AsyncSession, data: UserCreate) -> User:
    user = User(**data.model_dump())
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.exec(select(User))
    return list(result.all())


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def update_user(session: AsyncSession, user: User, data: UserUpdate) -> User:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def delete_user(session: AsyncSession, user: User) -> None:
    await session.delete(user)
    await session.commit()
