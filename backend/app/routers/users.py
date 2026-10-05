"""Administrative user management.

Self-service lives on `/auth/me`. Everything here is either admin-only or
addressed by a user id, in which case `require_self_or_admin` decides.
"""

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from app.crud import audit as audit_crud
from app.crud import session as session_crud
from app.crud import user as crud
from app.deps import AdminUser, CurrentUser, SessionDep, require_self_or_admin
from app.schemas.auth import ActiveUpdateRequest, RoleUpdateRequest
from app.schemas.user import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate, session: SessionDep, admin: AdminUser, request: Request
) -> UserRead:
    """Provision an account directly. Public signup is `/auth/register`."""
    if await crud.get_user_by_email(session, data.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )
    user = await crud.create_user(session, data)
    await audit_crud.record(
        session,
        actor=admin,
        action="user.create",
        target=user,
        detail={"role": user.role},
        request=request,
    )
    await session.commit()
    return UserRead.model_validate(user)


@router.get("", response_model=list[UserRead])
async def list_users(session: SessionDep, admin: AdminUser) -> list[UserRead]:
    return [UserRead.model_validate(u) for u in await crud.list_users(session)]


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: uuid.UUID, session: SessionDep, current: CurrentUser) -> UserRead:
    require_self_or_admin(user_id, current)
    user = await crud.get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserRead.model_validate(user)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID, data: UserUpdate, session: SessionDep, current: CurrentUser
) -> UserRead:
    require_self_or_admin(user_id, current)
    user = await crud.get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if data.email is not None:
        existing = await crud.get_user_by_email(session, data.email)
        if existing is not None and existing.id != user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with that email already exists.",
            )
    return UserRead.model_validate(await crud.update_user(session, user, data))


@router.patch("/{user_id}/role", response_model=UserRead)
async def update_role(
    user_id: uuid.UUID,
    data: RoleUpdateRequest,
    session: SessionDep,
    admin: AdminUser,
    request: Request,
) -> UserRead:
    """Promote or demote an account.

    Separate from the general PATCH precisely so `role` can never be smuggled
    in as one field among many on a profile edit.
    """
    user = await crud.get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.role == "admin" and data.role != "admin" and await crud.count_admins(session) <= 1:
        # Losing the last admin leaves the moderation queue permanently
        # unreachable, with no in-app way to appoint a replacement.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This is the only active administrator. Promote another before demoting this one.",
        )
    previous = user.role
    updated = await crud.set_role(session, user, data.role)
    await audit_crud.record(
        session,
        actor=admin,
        action="user.role_change",
        target=updated,
        detail={"from": previous, "to": updated.role},
        request=request,
    )
    await session.commit()
    return UserRead.model_validate(updated)


@router.patch("/{user_id}/active", response_model=UserRead)
async def update_active(
    user_id: uuid.UUID,
    data: ActiveUpdateRequest,
    session: SessionDep,
    admin: AdminUser,
    request: Request,
) -> UserRead:
    user = await crud.get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not data.is_active and user.role == "admin" and await crud.count_admins(session) <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This is the only active administrator and cannot be deactivated.",
        )
    updated = await crud.set_active(session, user, data.is_active)
    if not data.is_active:
        # `set_active` bumps token_version, which is what actually stops the
        # tokens. Closing the rows out keeps the table honest about it.
        await session_crud.revoke_all_for_user(session, updated.id, "deactivated")
    await audit_crud.record(
        session,
        actor=admin,
        action="user.activate" if data.is_active else "user.deactivate",
        target=updated,
        request=request,
    )
    await session.commit()
    return UserRead.model_validate(updated)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID, session: SessionDep, admin: AdminUser, request: Request
) -> None:
    """Hard-delete an account.

    Only accounts with no history can go: resumes and moderation records
    reference the user by foreign key, and the delete is refused with a 409
    while any of them survive. `PATCH /users/{id}/active` is the operation
    that always works, and the one to prefer.
    """
    user = await crud.get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.role == "admin" and await crud.count_admins(session) <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This is the only active administrator and cannot be deleted.",
        )
    blockers = await crud.count_blocking_references(session, user.id)
    if blockers:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_blocked_detail(blockers))
    # Audited *before* the delete, and with the email copied onto the entry:
    # once the row is gone the id explains nothing on its own.
    await audit_crud.record(
        session,
        actor=admin,
        action="user.delete",
        target=user,
        detail={"role": user.role},
        request=request,
    )
    await session_crud.revoke_all_for_user(session, user.id, "account-deleted")
    try:
        await crud.delete_user(session, user)
    except IntegrityError as exc:
        # The pre-check above should have caught this. It missed either because
        # a row was written between the count and the commit, or because a new
        # table started referencing `users.id` without being added to
        # `_BLOCKING_REFERENCES`. Either way the admin gets the 409 rather than
        # a constraint name in a 500, and the rollback drops the audit entry —
        # nothing happened, so nothing should be recorded as having happened.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This account still owns records elsewhere and cannot be deleted. "
                "Deactivate it instead with PATCH /users/{id}/active."
            ),
        ) from exc


def _blocked_detail(blockers: dict[str, int]) -> str:
    """Turn the blocking counts into something an admin can act on."""
    parts = [f"{count} {label}{'s' if count != 1 else ''}" for label, count in blockers.items()]
    if len(parts) > 1:
        owned = ", ".join(parts[:-1]) + f" and {parts[-1]}"
    else:
        owned = parts[0]
    return (
        f"This account still owns {owned}, so it cannot be deleted. "
        "Deactivate it instead with PATCH /users/{id}/active, "
        "or remove that data first."
    )
