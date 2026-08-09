"""Companies — public, community-contributed, admin-moderated.

Any authenticated user may propose a company; the slug index and the search
endpoint together keep the list from filling with near-duplicates.
"""

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.crud import company as crud
from app.deps import (
    AdminUser,
    CurrentUser,
    ModeratorUser,
    SessionDep,
    require_editable,
    require_submission_quota,
    require_visible_company,
    visible_scope,
)
from app.models.company import Company
from app.schemas.company import (
    CompanyCreate,
    CompanyRead,
    CompanyReject,
    CompanyUpdate,
)
from app.services.slug import InvalidCompanyNameError, slugify_company

router = APIRouter(prefix="/companies", tags=["companies"])


def _slug_or_422(name: str) -> str:
    try:
        return slugify_company(name)
    except InvalidCompanyNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


def _duplicate(existing: Company) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "detail": (
                f"'{existing.name}' is already listed. Use it instead of adding a duplicate."
            ),
            "existing": CompanyRead.model_validate(existing).model_dump(mode="json"),
        },
    )


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create_company(
    data: CompanyCreate, session: SessionDep, user: CurrentUser
) -> CompanyRead:
    """Propose a company. Admin submissions are approved immediately.

    A slug collision answers 409 carrying the existing row, so the client can
    offer it rather than leaving the user to guess the spelling that would have
    found it.
    """
    slug = _slug_or_422(data.name)
    existing = await crud.find_by_slug(session, slug)
    if existing is not None:
        raise _duplicate(existing)
    require_submission_quota(await crud.count_pending_for(session, user.id), user, "company")
    return CompanyRead.model_validate(await crud.create_company(session, data, author=user))


@router.get("", response_model=list[CompanyRead])
async def list_companies(
    session: SessionDep,
    user: CurrentUser,
    q: str | None = Query(default=None, description="Search names and slugs before adding."),
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(pending|approved|rejected)$"
    ),
) -> list[CompanyRead]:
    companies = await crud.list_companies(
        session, visible_scope(Company, user), search=q, status=status_filter
    )
    return [CompanyRead.model_validate(c) for c in companies]


@router.get("/lookup", response_model=CompanyRead | None)
async def lookup_company(
    session: SessionDep,
    user: CurrentUser,
    name: str = Query(min_length=1),
) -> CompanyRead | None:
    """Resolve a typed name to the company it would collide with, if any.

    Lets a "add company" form warn *before* submitting, which is a far better
    experience than a 409 after the user has filled in every field.
    """
    existing = await crud.find_by_slug(session, _slug_or_422(name))
    return CompanyRead.model_validate(existing) if existing else None


@router.get("/{company_id}", response_model=CompanyRead)
async def get_company(
    company_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> CompanyRead:
    company = await require_visible_company(session, company_id, user)
    return CompanyRead.model_validate(company)


@router.patch("/{company_id}", response_model=CompanyRead)
async def update_company(
    company_id: uuid.UUID, data: CompanyUpdate, session: SessionDep, user: CurrentUser
) -> CompanyRead:
    company = await require_visible_company(session, company_id, user)
    require_editable(company, user, "company")
    if data.name is not None:
        slug = _slug_or_422(data.name)
        clash = await crud.find_by_slug(session, slug)
        if clash is not None and clash.id != company.id:
            raise _duplicate(clash)
    return CompanyRead.model_validate(await crud.update_company(session, company, data))


@router.post("/{company_id}/approve", response_model=CompanyRead)
async def approve_company(
    company_id: uuid.UUID, session: SessionDep, moderator: ModeratorUser
) -> CompanyRead:
    company = await crud.get_company(session, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return CompanyRead.model_validate(
        await crud.set_moderation_status(session, company, status="approved", reviewer=moderator)
    )


@router.post("/{company_id}/reject", response_model=CompanyRead)
async def reject_company(
    company_id: uuid.UUID, data: CompanyReject, session: SessionDep, moderator: ModeratorUser
) -> CompanyRead:
    """Reject a submission, with a reason its contributor can read.

    Rejected rows are kept rather than deleted: the contributor needs to see
    why, and the slug stays claimed so the same duplicate is not re-proposed.
    """
    company = await crud.get_company(session, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return CompanyRead.model_validate(
        await crud.set_moderation_status(
            session, company, status="rejected", reviewer=moderator, reason=data.reason
        )
    )


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(company_id: uuid.UUID, session: SessionDep, admin: AdminUser) -> None:
    company = await crud.get_company(session, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    await crud.delete_company(session, company)
