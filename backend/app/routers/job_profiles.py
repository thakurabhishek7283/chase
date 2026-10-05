"""Job profiles — public postings, keyed by (company, requisition id)."""

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.crud import job_profile as crud
from app.deps import (
    AdminUser,
    CurrentUser,
    ModeratorUser,
    SessionDep,
    require_editable,
    require_submission_quota,
    require_visible_company,
    require_visible_job_profile,
    visible_scope,
)
from app.models.job_profile import JobProfile
from app.schemas.job_profile import (
    JobProfileCreate,
    JobProfileRead,
    JobProfileReject,
    JobProfileUpdate,
)

router = APIRouter(prefix="/job-profiles", tags=["job-profiles"])


def _duplicate(existing: JobProfile) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "detail": (
                f"'{existing.position_title}' is already listed for this company. "
                "Use the existing posting instead of adding a duplicate."
            ),
            "existing": JobProfileRead.model_validate(existing).model_dump(mode="json"),
        },
    )


@router.post("", response_model=JobProfileRead, status_code=status.HTTP_201_CREATED)
async def create_job_profile(
    data: JobProfileCreate, session: SessionDep, user: CurrentUser
) -> JobProfileRead:
    """Propose a posting under a company the caller can see.

    The company check runs first: a posting attached to a company that is
    rejected, or that belongs to someone else's pending queue, would be
    unreachable from the moment it was created.
    """
    await require_visible_company(session, data.company_id, user)
    existing = await crud.find_duplicate(
        session,
        company_id=data.company_id,
        external_job_id=data.external_job_id,
        position_title=data.position_title,
        location=data.location,
    )
    if existing is not None:
        raise _duplicate(existing)
    require_submission_quota(await crud.count_pending_for(session, user.id), user, "job profile")
    return JobProfileRead.model_validate(await crud.create_job_profile(session, data, author=user))


@router.get("", response_model=list[JobProfileRead])
async def list_job_profiles(
    session: SessionDep,
    user: CurrentUser,
    company_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(pending|approved|rejected)$"
    ),
) -> list[JobProfileRead]:
    jobs = await crud.list_job_profiles(
        session, visible_scope(JobProfile, user), company_id=company_id, status=status_filter
    )
    return [JobProfileRead.model_validate(j) for j in jobs]


@router.get("/{job_profile_id}", response_model=JobProfileRead)
async def get_job_profile(
    job_profile_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> JobProfileRead:
    job_profile = await require_visible_job_profile(session, job_profile_id, user)
    return JobProfileRead.model_validate(job_profile)


@router.patch("/{job_profile_id}", response_model=JobProfileRead)
async def update_job_profile(
    job_profile_id: uuid.UUID,
    data: JobProfileUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> JobProfileRead:
    job_profile = await require_visible_job_profile(session, job_profile_id, user)
    require_editable(job_profile, user, "job profile")

    # An edit can move a posting onto another posting's identity, so the same
    # duplicate check the create path runs has to run here too.
    merged_external = (
        data.external_job_id
        if "external_job_id" in data.model_fields_set
        else job_profile.external_job_id
    )
    clash = await crud.find_duplicate(
        session,
        company_id=job_profile.company_id,
        external_job_id=merged_external,
        position_title=data.position_title or job_profile.position_title,
        location=data.location if "location" in data.model_fields_set else job_profile.location,
    )
    if clash is not None and clash.id != job_profile.id:
        raise _duplicate(clash)
    return JobProfileRead.model_validate(await crud.update_job_profile(session, job_profile, data))


@router.post("/{job_profile_id}/approve", response_model=JobProfileRead)
async def approve_job_profile(
    job_profile_id: uuid.UUID, session: SessionDep, moderator: ModeratorUser
) -> JobProfileRead:
    job_profile = await crud.get_job_profile(session, job_profile_id)
    if job_profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job profile not found")
    return JobProfileRead.model_validate(
        await crud.set_moderation_status(
            session, job_profile, status="approved", reviewer=moderator
        )
    )


@router.post("/{job_profile_id}/reject", response_model=JobProfileRead)
async def reject_job_profile(
    job_profile_id: uuid.UUID,
    data: JobProfileReject,
    session: SessionDep,
    moderator: ModeratorUser,
) -> JobProfileRead:
    job_profile = await crud.get_job_profile(session, job_profile_id)
    if job_profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job profile not found")
    return JobProfileRead.model_validate(
        await crud.set_moderation_status(
            session, job_profile, status="rejected", reviewer=moderator, reason=data.reason
        )
    )


@router.delete("/{job_profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job_profile(
    job_profile_id: uuid.UUID, session: SessionDep, admin: AdminUser
) -> None:
    job_profile = await crud.get_job_profile(session, job_profile_id)
    if job_profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job profile not found")
    await crud.delete_job_profile(session, job_profile)
